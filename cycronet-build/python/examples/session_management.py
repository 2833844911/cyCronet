"""
Example: Session management and context manager usage
"""

from cronet_cloak_py import CronetClient


def main():
    client = CronetClient()

    # Using context manager (automatically closes session)
    print("Using context manager...")
    with client.create_session() as session:
        response = session.get("https://httpbin.org/get")
        print(f"Status: {response['status_code']}")
        # Session automatically closed when exiting context

    # Multiple sessions
    print("\nCreating multiple sessions...")
    session1 = client.create_session()
    session2 = client.create_session(timeout_ms=10000)

    # List active sessions
    sessions = client.list_sessions()
    print(f"Active sessions: {len(sessions)}")

    # Make requests with different sessions
    response1 = session1.get("https://httpbin.org/delay/1")
    print(f"Session 1 response: {response1['status_code']}")

    response2 = session2.get("https://httpbin.org/delay/1")
    print(f"Session 2 response: {response2['status_code']}")

    # Close sessions
    session1.close()
    session2.close()

    print(f"Active sessions after close: {len(client.list_sessions())}")


if __name__ == "__main__":
    main()
