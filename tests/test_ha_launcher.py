"""Exercise synthetic HA startup and reject a real non-proxy socket."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

Path('/data').mkdir(exist_ok=True)
Path('/data/options.json').write_text(json.dumps({'synthetic_ha_test': True}))
process = subprocess.Popen([sys.executable, '/app/launcher.py'])
try:
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError('HA test server exited')
        try:
            connection = socket.create_connection(('127.0.0.1', 8099), timeout=0.2)
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise AssertionError('HA test server did not start')
    with connection:
        connection.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\nX-Forwarded-For: 172.30.32.2\r\n\r\n')
        try:
            result = connection.recv(1024)
        except ConnectionResetError:
            result = b''
        assert result == b'', 'non-proxy connection received a response'
    print('PASS: synthetic HA startup rejects direct and spoofed proxy requests')
finally:
    process.terminate()
    process.wait(timeout=10)
