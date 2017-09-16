
def primes():
    n = 2
    while True:
        if all(n % div for div in range(2, n)):
            yield n
        n += 1

gen = primes()
for n in range(20):
    print(next(gen))
