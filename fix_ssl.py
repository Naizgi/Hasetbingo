import ssl
import certifi
import os

# Fix SSL certificate path
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

print(f"SSL Cert Path: {certifi.where()}")