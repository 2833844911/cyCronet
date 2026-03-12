"""
Example: Using proxy with Cronet-Cloak
"""

from cronet_cloak_py import CronetClient


def main():
    client = CronetClient()

    # Create session with HTTP proxy
    print("Creating session with HTTP proxy...")
    proxy_rules = "http://proxy.example.com:8080"
    session = client.create_session(proxy_rules=proxy_rules)

    # Make request through proxy
    print("Making request through proxy...")
    response = session.get("https://httpbin.org/ip")
    print(f"Status: {response['status_code']}")
    print(f"Response: {response['body']}")

    session.close()

    # Create session with SOCKS5 proxy with authentication
    print("\nCreating session with SOCKS5 proxy...")
    proxy_rules = "socks5://username:password@proxy.example.com:1080"
    session = client.create_session(proxy_rules=proxy_rules)

    response = session.get("https://httpbin.org/ip")
    print(f"Status: {response['status_code']}")

    session.close()


if __name__ == "__main__":
    main()
