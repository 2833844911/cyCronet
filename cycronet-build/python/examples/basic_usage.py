"""
Example: Basic usage of Cronet-Cloak Python client
"""

from cronet_cloak_py import CronetClient


def main():
    # Create client
    client = CronetClient()

    # Create a session
    print("Creating session...")
    session = client.create_session()

    # Make a GET request
    print("\nMaking GET request to https://httpbin.org/get")
    response = session.get("https://httpbin.org/get")

    print(f"Status Code: {response['status_code']}")
    print(f"Body: {response['body'][:200]}...")  # Print first 200 bytes

    # Make a POST request with headers
    print("\nMaking POST request to https://httpbin.org/post")
    headers = [
        ("user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
        ("content-type", "application/json"),
    ]
    body = b'{"key": "value"}'

    response = session.post("https://httpbin.org/post", headers=headers, body=body)
    print(f"Status Code: {response['status_code']}")
    print(f"Body: {response['body'][:200]}...")

    # Close session
    session.close()
    print("\nSession closed")


if __name__ == "__main__":
    main()
