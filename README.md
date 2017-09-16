# asyncchat
Asynchronous Telnet Chat Server

This is an example of using Python's `async` and `await` keywords *without* the use of asyncio or other framework. Requires Python3.6.

Run the server with the following:

```
python3.6 asynchat.py
```

Then connect with telnet as follows:

```
telnet 127.0.0.1 2323
```

If you open multiple connections you will be able to send chat messages between clients.

If you want to run the server on the internet, launch `asyncchat.py` as follows:

```
sudo python3.5 asynchat.py 0.0.0.0 23
```

Then you can connect with 

```python
telnet <your ip>
```
