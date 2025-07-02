import re
import json
from typing import Dict, Any, List, Tuple, Optional
import requests
from pathlib import Path

DATAFLOW_SCHEMA = {
    "name": "octratx",
    "description": "Tool for managing Octra wallet transactions",
    "entrypoint": "process_transaction",
    "input": {
        "properties": {
            "action": {
                "type": "string",
                "description": "Action to perform",
                "enum": ["send", "check_balance", "get_history"],
                "required": True
            },
            "to_address": {
                "type": "string",
                "description": "Recipient's Octra address (required for send action)",
                "pattern": "^oct[1-9A-HJ-NP-Za-km-z]{44}$"
            },
            "amount": {
                "type": "number",
                "description": "Amount to send (required for send action)",
                "minimum": 0.000001
            },
            "wallet_data": {
                "type": "json",
                "description": "open wallet.json and copy-paste the content here",
                "contentSchema": {
                    "type": "object",
                    "properties": {
                        "private_key": {
                            "type": "string",
                            "description": "Your Octra wallet private key"
                        },
                        "address": {
                            "type": "string",
                            "description": "Your Octra wallet address"
                        },
                        "rpc_url": {
                            "type": "string",
                            "description": "RPC endpoint URL (default: https://octra.network)",
                            "default": "https://octra.network"
                        }
                    },
                    "required": ["private_key", "address"]
                }
            }
        },
        "required": ["action"]
    }
}

class OctraWalletError(Exception):
    """Base exception for Octra wallet operations"""
    pass

class OctraWallet:
    def __init__(self, wallet_path: str = 'wallet.json', rpc_url: str = 'https://octra.network'):
        """
        Initialize the Octra wallet.
        
        Args:
            wallet_path: Path to wallet.json file
            rpc_url: RPC endpoint URL
        """
        self.wallet_path = wallet_path
        self.rpc_url = rpc_url
        self.private_key = None
        self.address = None
        self.signing_key = None
        self.public_key = None
        self.session = requests.Session()
        self.balance_cache = None
        self.nonce_cache = None
        self.last_update = 0
        self.transaction_history = []
        self.last_history_update = 0
        
        # Constants
        self.MICROUNIT = 1_000_000
        self.ADDRESS_PATTERN = re.compile(r"^oct[1-9A-HJ-NP-Za-km-z]{44}$")
        self.AMOUNT_PATTERN = re.compile(r"^\d+(\.\d+)?$")

    def load_wallet(self) -> None:
        """Load wallet from file"""
        try:
            if not Path(self.wallet_path).exists():
                raise OctraWalletError(f"Wallet file not found: {self.wallet_path}")
            
            with open(self.wallet_path, 'r') as f:
                wallet_data = json.load(f)
                self.private_key = wallet_data.get('private_key')
                self.address = wallet_data.get('address')
                
            if not self.private_key or not self.address:
                raise OctraWalletError("Invalid wallet file format")
                
        except json.JSONDecodeError:
            raise OctraWalletError("Invalid wallet file format")
        except Exception as e:
            raise OctraWalletError(f"Failed to load wallet: {str(e)}")

    def get_status(self, force_refresh: bool = False) -> Tuple[Optional[int], Optional[float]]:
        """
        Get current wallet status (nonce and balance)
        
        Args:
            force_refresh: Force refresh of cached values
            
        Returns:
            Tuple of (nonce, balance)
        """
        try:
            response = self.session.get(f"{self.rpc_url}/v1/account/{self.address}")
            response.raise_for_status()
            data = response.json()
            
            balance = float(data['balance']) / self.MICROUNIT
            nonce = int(data['nonce'])
            
            return nonce, balance
            
        except Exception as e:
            raise OctraWalletError(f"Failed to get wallet status: {str(e)}")

    def send_transaction(self, to_address: str, amount: float) -> Dict[str, Any]:
        """
        Send a single transaction
        
        Args:
            to_address: Recipient address
            amount: Amount to send
            
        Returns:
            Transaction result
        """
        if not self.ADDRESS_PATTERN.match(to_address):
            raise OctraWalletError("Invalid recipient address")
            
        if amount <= 0:
            raise OctraWalletError("Amount must be positive")
            
        try:
            # This is a simplified version - in reality you'd need to:
            # 1. Create and sign the transaction
            # 2. Submit to network
            # 3. Wait for confirmation
            payload = {
                "from": self.address,
                "to": to_address,
                "amount": str(int(amount * self.MICROUNIT)),
                "nonce": self.get_status()[0]
            }
            
            response = self.session.post(
                f"{self.rpc_url}/v1/transactions", 
                json=payload
            )
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            raise OctraWalletError(f"Transaction failed: {str(e)}")

    def send_multiple_transactions(self, recipients: List[Tuple[str, float]], batch_size: int = 5) -> Dict[str, Any]:
        """
        Send multiple transactions in batches
        
        Args:
            recipients: List of (address, amount) tuples
            batch_size: Number of transactions per batch
            
        Returns:
            Batch transaction results
        """
        results = []
        for i in range(0, len(recipients), batch_size):
            batch = recipients[i:i + batch_size]
            for addr, amt in batch:
                result = self.send_transaction(addr, amt)
                results.append(result)
        return {"batch_results": results}

    def get_history(self) -> List[Dict[str, Any]]:
        """Get transaction history"""
        try:
            response = self.session.get(
                f"{self.rpc_url}/v1/account/{self.address}/transactions"
            )
            response.raise_for_status()
            return response.json()['transactions']
        except Exception as e:
            raise OctraWalletError(f"Failed to get history: {str(e)}")

    def close(self) -> None:
        """Close wallet session"""
        if self.session:
            self.session.close()

def process_transaction(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entrypoint for the tool
    
    Args:
        input_data: Dictionary containing the input values matching the schema
        
    Returns:
        Operation result

    Example wallet_data:
        {
            "priv": "private-key-here",
            "addr": "octxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "rpc": "https://octra.network"
        }
    """
    wallet = OctraWallet(input_data.get('wallet_data'))
    
    try:
        wallet.load_wallet()
        
        action = input_data['action']
        
        if action == 'check_balance':
            nonce, balance = wallet.get_status()
            return {
                "balance": balance,
                "nonce": nonce,
                "address": wallet.address
            }
            
        elif action == 'send':
            if not input_data.get('to_address') or not input_data.get('amount'):
                raise OctraWalletError("to_address and amount required for send action")
                
            result = wallet.send_transaction(
                input_data['to_address'],
                float(input_data['amount'])
            )
            return result
            
        elif action == 'get_history':
            history = wallet.get_history()
            return {"history": history}
            
        else:
            raise OctraWalletError(f"Unknown action: {action}")
            
    except Exception as e:
        raise OctraWalletError(f"Operation failed: {str(e)}")
        
    finally:
        wallet.close()

def example_usage():
    """Example usage of the Octra wallet module"""
    wallet = OctraWallet()
    
    try:
        wallet.load_wallet()
        print(f"Loaded wallet: {wallet.address}")
        
        nonce, balance = wallet.get_status()
        print(f"Balance: {balance:.6f} OCT, Nonce: {nonce}")
        
        history = wallet.get_history()
        print(f"Transaction history: {len(history)} transactions")
        
    except OctraWalletError as e:
        print(f"Wallet error: {e}")
    finally:
        wallet.close()

if __name__ == "__main__":
    example_usage()