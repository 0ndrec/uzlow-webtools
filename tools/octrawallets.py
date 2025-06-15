import os
import hashlib
import hmac
import secrets
import base64
from typing import List, Tuple
from nacl.signing import SigningKey
from nacl.public import PrivateKey
import ecdsa
from ecdsa.curves import SECP256k1, NIST256p
from ecdsa.keys import SigningKey as ECDSASigningKey
from datetime import datetime
from pathlib import Path


WORDLIST_PATH = Path(__file__).parent.parent / "static" / "wordlist.txt"
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

DATAFLOW_SCHEMA = {
    "entrypoint": "generate",
    "input": None,
    "output": {
        "type": "object",
        "properties": {
            "mnemonic": {"type": "array","items": {"type": "string"},"minItems": 12,"maxItems": 24},
            "seed_hex": {"type": "string", "format": "hex"},
            "master_chain_hex": {"type": "string", "format": "hex"},
            "private_key_hex": {"type": "string", "format": "hex"},
            "public_key_hex": {"type": "string", "format": "hex"},
            "private_key_b64": {"type": "string", "format": "base64"},
            "public_key_b64": {"type": "string", "format": "base64"},
            "address": {"type": "string", "pattern": "^oct[a-zA-Z0-9]+$"},
            "entropy_hex": {"type": "string", "format": "hex"},
            "test_message": {"type": "string"},
            "test_signature": {"type": "string", "format": "base64"},
            "signature_valid": {"type": "boolean"}
        },
    }
}

def load_wordlist(filename: str = WORDLIST_PATH) -> List[str]:
    if not os.path.exists(filename):
        raise FileNotFoundError(f"File {filename} not found!")
    
    with open(filename, 'r', encoding='utf-8') as f:
        words = [line.strip() for line in f if line.strip()]
    
    if len(words) != 2048:
        raise ValueError(f"Wordlist must contain 2048 words, found: {len(words)}")
    
    return words

def generate_entropy(strength: int = 128) -> bytes:
    if strength not in [128, 160, 192, 224, 256]:
        raise ValueError("Strength must be 128, 160, 192, 224 or 256 bits")
    return secrets.token_bytes(strength // 8)

def entropy_to_mnemonic(entropy: bytes, wordlist: List[str]) -> List[str]:
    checksum_bits = len(entropy) * 8 // 32
    checksum = hashlib.sha256(entropy).digest()
    checksum_int = int.from_bytes(checksum[:1], 'big') >> (8 - checksum_bits)
    
    entropy_int = int.from_bytes(entropy, 'big')
    combined = (entropy_int << checksum_bits) | checksum_int
    
    mnemonic = []
    bits = len(entropy) * 8 + checksum_bits
    
    for i in range(bits // 11):
        word_index = (combined >> (bits - (i + 1) * 11)) & 0x7FF
        mnemonic.append(wordlist[word_index])
    
    return mnemonic

def mnemonic_to_seed(mnemonic: List[str], passphrase: str = "") -> bytes:
    mnemonic_str = " ".join(mnemonic)
    salt = ("mnemonic" + passphrase).encode('utf-8')
    seed = hashlib.pbkdf2_hmac('sha512', mnemonic_str.encode('utf-8'), salt, 2048)
    return seed

def derive_master_key(seed: bytes) -> Tuple[bytes, bytes]:
    key = b"Octra seed"
    mac = hmac.new(key, seed, hashlib.sha512).digest()
    master_private_key = mac[:32]
    master_chain_code = mac[32:]
    return master_private_key, master_chain_code

def derive_child_key_ed25519(private_key: bytes, chain_code: bytes, index: int) -> Tuple[bytes, bytes]:
    if index >= 0x80000000:
        data = b'\x00' + private_key + index.to_bytes(4, 'big')
    else:
        signing_key = SigningKey(private_key)
        public_key = signing_key.verify_key.encode()
        data = public_key + index.to_bytes(4, 'big')
    
    mac = hmac.new(chain_code, data, hashlib.sha512).digest()
    child_private_key = mac[:32]
    child_chain_code = mac[32:]
    
    return child_private_key, child_chain_code

def derive_path(seed: bytes, path: List[int]) -> Tuple[bytes, bytes]:
    key, chain = derive_master_key(seed)
    for index in path:
        key, chain = derive_child_key_ed25519(key, chain, index)
    return key, chain

def get_network_type_name(network_type: int) -> str:
    if network_type == 0:
        return "MainCoin"
    elif network_type == 1:
        return f"SubCoin {network_type}"
    elif network_type == 2:
        return f"Contract {network_type}"
    elif network_type == 3:
        return f"Subnet {network_type}"
    elif network_type == 4:
        return f"Account {network_type}"
    else:
        return f"Unknown {network_type}"

def derive_for_network(seed: bytes, network_type: int = 0, network: int = 0, 
                      contract: int = 0, account: int = 0, index: int = 0,
                      token: int = 0, subnet: int = 0) -> dict:
    coin_type = 0 if network_type == 0 else network_type
    
    base_path = [
        0x80000000 | 345,
        0x80000000 | coin_type,
        0x80000000 | network,
    ]
    contract_path = [0x80000000 | contract, 0x80000000 | account]
    optional_path = [0x80000000 | token, 0x80000000 | subnet]
    final_path = [index]
    
    full_path = base_path + contract_path + optional_path + final_path
    
    derived_key, derived_chain = derive_path(seed, full_path)
    
    signing_key = SigningKey(derived_key)
    verify_key = signing_key.verify_key
    
    derived_address = create_octra_address(verify_key.encode())
    
    return {
        'private_key': derived_key,
        'chain_code': derived_chain,
        'public_key': verify_key.encode(),
        'address': derived_address,
        'path': full_path,
        'network_type_name': get_network_type_name(network_type),
        'network': network,
        'contract': contract,
        'account': account,
        'index': index
    }

def base58_encode(data: bytes) -> str:
    if not data:
        return ""
    
    num = int.from_bytes(data, 'big')
    encoded = ""
    
    while num > 0:
        num, remainder = divmod(num, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    
    for byte in data:
        if byte == 0:
            encoded = '1' + encoded
        else:
            break
    
    return encoded

def create_octra_address(public_key: bytes) -> str:
    hash_digest = hashlib.sha256(public_key).digest()
    base58_hash = base58_encode(hash_digest)
    address = "oct" + base58_hash
    return address

def verify_address_format(address: str) -> bool:
    if not address.startswith("oct"):
        return False
    if len(address) < 20 or len(address) > 50:
        return False
    base58_part = address[3:]
    for char in base58_part:
        if char not in BASE58_ALPHABET:
            return False
    return True


def generate():
    wordlist = load_wordlist()
    entropy = generate_entropy(128)
    mnemonic = entropy_to_mnemonic(entropy, wordlist)
    seed = mnemonic_to_seed(mnemonic)
    master_private, master_chain = derive_master_key(seed)
    
    signing_key = SigningKey(master_private)
    verify_key = signing_key.verify_key
    private_key_raw = signing_key.encode()
    public_key_raw = verify_key.encode()
    address = create_octra_address(public_key_raw)
    
    if not verify_address_format(address):
        raise ValueError("Invalid address format generated")
    
    test_message = '{"from":"test","to":"test","amount":"1000000","nonce":1}'
    signed = signing_key.sign(test_message.encode())
    signature_b64 = base64.b64encode(signed.signature).decode()
    
    try:
        verify_key.verify(test_message.encode(), signed.signature)
        signature_valid = True
    except:
        signature_valid = False
    
    return {
        'mnemonic': mnemonic,
        'seed_hex': seed.hex(),
        'master_chain_hex': master_chain.hex(),
        'private_key_hex': private_key_raw.hex(),
        'public_key_hex': public_key_raw.hex(),
        'private_key_b64': base64.b64encode(private_key_raw).decode(),
        'public_key_b64': base64.b64encode(public_key_raw).decode(),
        'address': address,
        'entropy_hex': entropy.hex(),
        'test_message': test_message,
        'test_signature': signature_b64,
        'signature_valid': signature_valid
    }


def save_wallet(data):
    
    content = f"""OCTRA WALLET
    {"=" * 50}

    SECURITY WARNING: KEEP THIS FILE SECURE AND NEVER SHARE YOUR PRIVATE KEY

    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    Address Format: oct + Base58(SHA256(pubkey))

    Mnemonic: {' '.join(data['mnemonic'])}
    Private Key (B64): {data['private_key_b64']}
    Public Key (B64): {data['public_key_b64']}
    Address: {data['address']}

    Technical Details:
    Entropy: {data['entropy_hex']}
    Signature Algorithm: Ed25519
    Derivation: BIP39-compatible (PBKDF2-HMAC-SHA512, 2048 iterations)
    """
    
    return content.encode('utf-8')

def derive(data):
    seed_hex = data.get('seed_hex', '')
    network_type = data.get('network_type', 0)
    index = data.get('index', 0)
    
    try:
        seed = bytes.fromhex(seed_hex)
        derived = derive_for_network(
            seed=seed,
            network_type=network_type,
            network=0,
            contract=0,
            account=0,
            index=index
        )
        
        return {
            'success': True,
            'address': derived['address'],
            'path': '/'.join(str(i & 0x7FFFFFFF) + ("'" if i & 0x80000000 else '') for i in derived['path']),
            'network_type_name': derived['network_type_name']
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


if __name__ == "__main__":
    print(generate())