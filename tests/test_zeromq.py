import unittest
import threading
import time
import zmq

class TestZeroMQ(unittest.TestCase):
    def setUp(self):
        self.context = zmq.Context() 
        self.sockets = [] 

    def create_socket(self, socket_type):
        sock = self.context.socket(socket_type)
        self.sockets.append(sock)
        return sock

    def tearDown(self):
        for sock in self.sockets:
            if not sock.closed:
                sock.close(linger=0)
        self.context.destroy(linger=0)

    def test_req_rep_threaded(self):
        """Test the Request-Reply (REQ/REP) pattern using a background server thread."""
        rep_socket = self.create_socket(zmq.REP)
        req_socket = self.create_socket(zmq.REQ)
        rep_socket.rcvtimeo = 1000 # avoid hanging on failure
        req_socket.rcvtimeo = 1000
        addr = "inproc://req-rep-threaded"
        rep_socket.bind(addr)
        req_socket.connect(addr)
        def server_worker():
            try:
                msg = rep_socket.recv()
                rep_socket.send(msg + b" world")
            except zmq.Again:
                pass  # Handle timeout gracefully if it occurs
        server_thread = threading.Thread(target=server_worker)
        server_thread.start()
        req_socket.send(b"hello")
        reply = req_socket.recv()
        self.assertEqual(reply, b"hello world")
        server_thread.join()

    def test_pub_sub(self):
        """Test the Publish-Subscribe (PUB/SUB) pattern with topic filtering."""
        pub = self.create_socket(zmq.PUB)
        sub1 = self.create_socket(zmq.SUB)
        sub2 = self.create_socket(zmq.SUB)
        pub.rcvtimeo = 1000
        sub1.rcvtimeo = 1000
        sub2.rcvtimeo = 1000
        addr = "inproc://pub-sub-test"
        pub.bind(addr)
        sub1.connect(addr)
        sub2.connect(addr)
        sub1.setsockopt(zmq.SUBSCRIBE, b"topic_a") # sub1 subscribes to "topic_a"
        sub2.setsockopt(zmq.SUBSCRIBE, b"topic_b") # sub2 subscribes to "topic_b"
        time.sleep(0.1) # avoid "slow joiner" syndrome
        pub.send_multipart([b"topic_a", b"message for A"])
        pub.send_multipart([b"topic_b", b"message for B"])
        pub.send_multipart([b"topic_c", b"message for C (ignored)"])
        topic_a, msg_a = sub1.recv_multipart() # sub1 should receive its message
        self.assertEqual(topic_a, b"topic_a")
        self.assertEqual(msg_a, b"message for A")
        topic_b, msg_b = sub2.recv_multipart() # sub2 should receive its message
        self.assertEqual(topic_b, b"topic_b")
        self.assertEqual(msg_b, b"message for B")
        with self.assertRaises(zmq.Again): # Neither should receive the unsubscribed topic_c, so they should timeout/error on next read
            sub1.recv(flags=zmq.NOBLOCK)
        with self.assertRaises(zmq.Again):
            sub2.recv(flags=zmq.NOBLOCK)

    def test_push_pull(self):
        """Test the Pipeline (PUSH/PULL) pattern distributing tasks to pullers."""
        push = self.create_socket(zmq.PUSH)
        pull1 = self.create_socket(zmq.PULL)
        pull2 = self.create_socket(zmq.PULL)
        pull1.rcvtimeo = 1000
        pull2.rcvtimeo = 1000
        addr = "inproc://push-pull-test"
        push.bind(addr)
        pull1.connect(addr)
        pull2.connect(addr)
        time.sleep(0.1)
        push.send(b"task 1")
        push.send(b"task 2")
        received = []
        for puller in (pull1, pull2):
            try:
                received.append(puller.recv(flags=zmq.NOBLOCK))
            except zmq.Again:
                pass
        for puller in (pull1, pull2):
            try:
                received.append(puller.recv(flags=zmq.NOBLOCK))
            except zmq.Again:
                pass
        self.assertIn(b"task 1", received)
        self.assertIn(b"task 2", received)
        self.assertEqual(len(received), 2)

    def test_pair(self):
        """Test the Peer-to-Peer (PAIR) pattern for bidirectional connection."""
        pair1 = self.create_socket(zmq.PAIR)
        pair2 = self.create_socket(zmq.PAIR)
        pair1.rcvtimeo = 1000
        pair2.rcvtimeo = 1000
        addr = "inproc://pair-test"
        pair1.bind(addr)
        pair2.connect(addr)
        pair1.send(b"hello from 1")
        self.assertEqual(pair2.recv(), b"hello from 1")
        pair2.send(b"hello from 2")
        self.assertEqual(pair1.recv(), b"hello from 2")

    def test_json_serialization(self):
        """Test PyZMQ's built-in JSON serialization capabilities."""
        rep = self.create_socket(zmq.REP)
        req = self.create_socket(zmq.REQ)
        rep.rcvtimeo = 1000
        req.rcvtimeo = 1000
        addr = "inproc://json-test"
        rep.bind(addr)
        req.connect(addr)
        payload = {
            "status": "success",
            "code": 200,
            "data": ["item1", "item2"],
            "nested": {"active": True}
        }
        req.send_json(payload)
        received = rep.recv_json()
        self.assertEqual(received, payload)
        response = {"message": "processed"}
        rep.send_json(response)
        reply = req.recv_json()
        self.assertEqual(reply, response)

if __name__ == "__main__":
    unittest.main()
