from collections import deque  # doubled ended queue

import select
import socket

# The Reader object is 'awaited' on in a coroutine, and tells the
# Server instance to suspend the coroutine until there is data
# available on the socket.
class Reader:
    """An awaitable that reads from a socket."""
    readers = set()  # All readers awaiting IO

    def __init__(self, socket, max_bytes):
        self.socket = socket
        self.max_bytes = max_bytes

    def fileno(self):
        """Get file descriptor integer."""
        # Allows this object to be used in 'select'.
        return self.socket.fileno()

    def __await__(self):
        self.readers.add(self)
        try:
            data = yield self  # Get socket data from server
            return data  # Return value of await statement
        finally:
            self.readers.discard(self)


# The Writer object is 'awaited' on in a coroutine, and tells the
# Server to suspend the coroutine until data can be sent.
# In practice, sockets are almost always available to be written to,
# but if network buffers are full we may have to wait for a send to
# complete.
class Writer:
    """An awaitable that writes to a socket."""
    writers = set()  # All writers awaiting IO

    def __init__(self, socket, data):
        self.socket = socket
        self.data = data

    def fileno(self):
        """Get file descriptor integer."""
        return self.socket.fileno()

    def __await__(self):
        writers = self.writers
        # If something else is writing on that socket wait until
        # socket is free.
        while any(self.socket==socket for writer in writers):
            yield
        writers.add(self)
        try:
            # Write data in multiple batches if required.
            while self.data:
                sent_bytes = yield self  # Wait for server to write data
                self.data = self.data[sent_bytes:]
        finally:
            writers.discard(self)


# This Server object is essentially the 'loop' or the 'kernel' that
# runs coroutines and waits for IO.
class Server:
    """Run the server and the clients."""

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self._tasks = deque()

    @classmethod
    def make_socket(cls, host, port):
        """Make a server socket."""
        _socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _socket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR, 1)
        _socket.bind((host, port))
        _socket.listen(1)
        return _socket

    @classmethod
    def accept(cls, server_socket):
        """Accept incoming connection."""
        client_socket, client_address = server_socket.accept()
        connection = Connection(client_socket, client_address)
        return connection

    @classmethod
    def wait_for_io(cls):
        """Wait for any sockets available to read / write."""
        rlist, wlist, _ = select.select(
            Reader.readers,
            Writer.writers,
            [],
            60
        )
        return rlist, wlist

    def add_task(self, coro, send=None):
        """Add a coroutine to run on the next loop."""
        self._tasks.append((coro, send))

    def _run_coroutines(self):
        """Run coroutines until all are awaiting or stalled."""
        # Send stored value to coroutines and run them until the next
        # awaitable. If a coroutine yields None, it is 'stalled'.
        stalled = []
        while self._tasks:
            coro, send = self._tasks.popleft()
            try:
                awaiting = coro.send(send)
            except StopIteration:
                # Coroutine completed.
                continue
            else:
                if awaiting is None:
                    # Coroutine yielded with None, it is stalled.
                    stalled.append((coro, None))
                else:
                    awaiting.coro = coro
                    # Stalled coroutines may be able to run now.
                    self._tasks.extend(stalled)
        # Stash stalled coroutine for later.
        self._tasks.extend(stalled)

    def run_forever(self):
        """Run the server forever (or until you press Ctrl+C)."""
        server_socket = self.make_socket(self.host, self.port)
        Reader.readers.add(server_socket)

        print('server running')
        print(f"connect with 'telnet {self.host} {self.port}'")

        # Note: this is analogous to an asyncio 'loop'.
        while True:
            self._run_coroutines()
            readers, writers = self.wait_for_io()

            for reader in readers:
                if reader is server_socket:
                    # Pending new connection.
                    connection = self.accept(server_socket)
                    coro = connection.run()
                    self.add_task(coro)
                else:
                    # Data available. Read it and send it to coroutine.
                    data = reader.socket.recv(reader.max_bytes)
                    self.add_task(reader.coro, data)

            for writer in writers:
                # Socket may be written to, write data and send
                # bytes sent count to coroutine next cycle.
                bytes_sent = writer.socket.send(writer.data)
                self.add_task(writer.coro, bytes_sent)


class Connection:
    """A Chat client connection."""
    chatters = set()

    def __init__(self, socket, client_address):
        self._socket = socket
        self.client_address = client_address
        self.name = None

    def recv(self, max_bytes):
        """Return a reader awaitable that reads data."""
        return Reader(self._socket, max_bytes)

    def sendall(self, data):
        """Return a writer awaitable to send data."""
        return Writer(self._socket, data)

    async def readline(self):
        """Coroutine to read a line."""
        chars = []
        while 1:
            char = await self.recv(1)
            chars.append(char)
            if char == b'\n' or char == b'':
                break
        return b''.join(chars).decode('ascii', 'replace')

    async def writeline(self, text):
        """Coroutine to write a line."""
        await self.sendall(text.encode('ascii', 'replace') + b'\r\n')

    async def broadcast(self, text):
        """Coroutine to broadcast a line (send to other clients)."""
        print(text)  # Let's us see whats going in in the server
        line_bytes = text.encode('ascii', 'replace') + b'\r\n'
        for connection in self.chatters:
            if connection is not self:
                await connection.sendall(line_bytes)

    async def run(self):
        """print connected / leave messages and run chat loop."""
        print(f'{self.client_address} connected')
        try:
            await self.chat_loop()
        finally:
            print(f'{self.client_address} left')

    async def chat_loop(self):
        """Main loop of chat client."""
        name = await self.get_user_name()
        await self.writeline(f'Welcome {name}!')
        await self.log_chatters()
        await self.broadcast(f'@{name} entered room')
        self.name = name
        self.chatters.add(self)
        try:
            while True:
                line = await self.readline()
                if line == '':
                    break
                await self.broadcast(f'[{name}]\t{line.rstrip()}')
        finally:
            self.chatters.pop(self)
        await self.broadcast(f'@{name} left the room')

    async def log_chatters(self):
        """Tell the user who is online."""
        names = sorted(chatter.name for name in self.chatters)
        for name in names:
            await self.writeline(f'@{name} is here')

    async def get_user_name(self):
        """Get a user name."""
        await self.writeline('Please enter your name...')
        while True:
            name = await self.readline()
            name = name.strip().lower()[:16]
            if name not in self.chatters:
                break
            await self.writeline(
                'That name is taken, please enter another...'
            )
        return name


if __name__ == "__main__":
    server = Server('127.0.0.1', 8000)
    server.run_forever()
