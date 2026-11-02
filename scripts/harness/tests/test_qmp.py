import importlib.util
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

spec = importlib.util.spec_from_file_location('qmp_type', Path(__file__).resolve().parents[2] / 'qmp-type.py')
qmp_type = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qmp_type)


class QMPTests(unittest.TestCase):
    def test_events_survive_commands_and_read_timeouts(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'control.sock')
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(path)
            listener.listen(1)
            release = threading.Event()
            errors = []
            def serve():
                try:
                    connection, _ = listener.accept()
                    with connection, connection.makefile('rb') as stream:
                        connection.sendall(b'{"QMP":{}}\n')
                        self.assertEqual(json.loads(stream.readline())['execute'], 'qmp_capabilities')
                        connection.sendall(b'{"event":"RESET"}\n{"return":{}}\n{"event":')
                        self.assertTrue(release.wait(3))
                        connection.sendall(b'"RESUME"}\n')
                        self.assertEqual(json.loads(stream.readline())['execute'], 'query-status')
                        connection.sendall(b'{"return":{"status":"running"}}\n')
                        self.assertEqual(stream.readline(), b'')
                except BaseException as error:
                    errors.append(error)
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            execute = qmp_type.qmp(path)
            try:
                self.assertEqual(execute.next_event(.1)['event'], 'RESET')
                with self.assertRaises(TimeoutError):
                    execute.next_event(.03)
                release.set()
                self.assertEqual(execute.next_event(2)['event'], 'RESUME')
                self.assertEqual(execute('query-status'), {'status': 'running'})
            finally:
                execute.close()
                release.set()
                thread.join(3)
                listener.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
