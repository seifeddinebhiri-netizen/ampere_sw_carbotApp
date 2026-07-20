"""Generate a local CA and the certificates for the lab.

Run once:  python make_certs.py

Produces, in ./certs/ :
    ca.crt / ca.key          the Certificate Authority -- our root of trust
    broker.crt / broker.key  identifies the CLOUD BROKER (for TLS)
    backend.crt / backend.key  identifies the BACKEND     (for mTLS)
    car.crt / car.key          identifies the CAR         (for mTLS)

This is a TOY CA. Real fleets run a hardened CA with hardware key storage, and
provision vehicle certs on the production line. Same concepts, vastly more
process. Never use these files outside your laptop.
"""

import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_DIR = Path(__file__).resolve().parent / "certs"
CERT_DIR.mkdir(exist_ok=True)

VALID_DAYS = 3650


def _key() -> rsa.RSAPrivateKey:
    # RSA 2048: universally supported by brokers. Ed25519 is nicer but support
    # is patchier -- not the place to be clever.
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _write(name: str, cert: x509.Certificate, key: rsa.RSAPrivateKey) -> None:
    (CERT_DIR / f"{name}.crt").write_bytes(
        cert.public_bytes(serialization.Encoding.PEM)
    )
    # No passphrase on the key: this is a lab. In production the key would be
    # encrypted at rest and loaded from a secrets manager or a hardware module.
    (CERT_DIR / f"{name}.key").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    print(f"  wrote certs/{name}.crt and certs/{name}.key")


def make_ca() -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    """The CA is the root of trust.

    Everyone (broker, backend, car) is configured to trust ca.crt. A certificate
    is believed because the CA SIGNED it -- that's the whole trick. Trust one
    thing, and it vouches for everything else.
    """
    key = _key()
    name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MyCarBot Lab"),
        x509.NameAttribute(NameOID.COMMON_NAME, "MyCarBot Lab CA"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)                      # self-signed: issuer == subject
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))  # clock skew
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None),
                       critical=True)
        .sign(key, hashes.SHA256())
    )
    _write("ca", cert, key)
    return cert, key


def make_cert(name: str, common_name: str, ca_cert: x509.Certificate,
              ca_key: rsa.RSAPrivateKey, server: bool = False) -> None:
    """Issue a certificate signed by our CA.

    common_name matters enormously:
      - for the BROKER it must match the hostname clients connect to
        ("localhost"), or TLS verification fails. This is the #1 TLS gotcha.
      - for CLIENTS it becomes their IDENTITY. With
        `use_identity_as_username true`, Mosquitto uses this string as the
        username -- so the CN must match your ACL entries exactly.
    """
    key = _key()
    subject = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MyCarBot Lab"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)           # signed BY the CA
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                       critical=True)
    )

    if server:
        # SANs are what modern TLS actually checks -- CN alone is deprecated.
        # Both names + the loopback IP, so any of them work.
        builder = builder.add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("127.0.0.1"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )

    cert = builder.sign(ca_key, hashes.SHA256())
    _write(name, cert, key)


if __name__ == "__main__":
    print("creating CA...")
    ca_cert, ca_key = make_ca()

    print("creating broker certificate (CN must match the hostname)...")
    make_cert("broker", "localhost", ca_cert, ca_key, server=True)

    print("creating client certificates (CN = identity = ACL username)...")
    # These CNs are deliberately the SAME strings as your existing ACL users.
    # That's what lets mTLS slot into the ACL you already wrote.
    make_cert("backend", "backend", ca_cert, ca_key)
    make_cert("car", "car_TESTVIN123", ca_cert, ca_key)

    print(f"\ndone -- files in {CERT_DIR}")