#!/usr/bin/env python3
"""
Octra Wallet Module
A clean Python module for interacting with the Octra network without TUI dependencies.
"""

import json
import base64
import hashlib
import time
import re
import random
import asyncio
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
import nacl.signing


DATAFLOW_SCHEMA = {
    "name": "octratx",
    "description": "Octra wallet client for managing transactions and balances",
    "entrypoint": "process_transaction",  # Main function to be called
    "input": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send", "status", "history", "pending", "wallet_info"]
            },
            "to_address": {"type": "string"},
            "amount": {"type": "number"},
            "limit": {"type": "integer", "default": 20},
            "wallet_path": {"type": "string", "default": "wallet.json"}
        },
        "required": ["action"]
    },
    "output": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "data": {"type": "object"},
            "error": {"type": "string"}
        }
    }
}


class OctraWalletError(Exception):
    """Base exception for Octra wallet operations"""
    pass


class OctraWallet:
    """
    Octra wallet client for managing transactions and balances.
    """
    
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
        self.session = None
        self.balance_cache = None
        self.nonce_cache = None
        self.last_update = 0
        self.transaction_history = []
        self.last_history_update = 0
        
        # Constants
        self.MICROUNIT = 1_000_000
        self.ADDRESS_PATTERN = re.compile(r"^oct[1-9A-HJ-NP-Za-km-z]{44}$")
        self.AMOUNT_PATTERN = re.compile(r"^\d+(\.\d+)?$")
        
    def load_wallet(self) -> bool:
        """
        Load wallet from JSON file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(self.wallet_path, 'r') as f:
                data = json.load(f)
            
            self.private_key = data.get('priv')
            self.address = data.get('addr')
            self.rpc_url = data.get('rpc', self.rpc_url)
            
            if not self.private_key or not self.address:
                raise OctraWalletError("Invalid wallet data")
            
            self.signing_key = nacl.signing.SigningKey(base64.b64decode(self.private_key))
            self.public_key = base64.b64encode(self.signing_key.verify_key.encode()).decode()
            
            return True
        except Exception as e:
            raise OctraWalletError(f"Failed to load wallet: {e}")
    
    def save_wallet(self, filename: Optional[str] = None) -> str:
        """
        Save wallet to JSON file.
        
        Args:
            filename: Optional custom filename
            
        Returns:
            str: Filename of saved wallet
        """
        if not filename:
            filename = f"octra_wallet_{int(time.time())}.json"
        
        wallet_data = {
            'priv': self.private_key,
            'addr': self.address,
            'rpc': self.rpc_url
        }
        
        with open(filename, 'w') as f:
            json.dump(wallet_data, f, indent=2)
        
        return filename
    
    async def _request(self, method: str, path: str, data: Optional[Dict] = None, timeout: int = 10) -> Tuple[int, str, Optional[Dict]]:
        """
        Make HTTP request to RPC endpoint.
        
        Args:
            method: HTTP method
            path: API path
            data: Request data for POST
            timeout: Request timeout
            
        Returns:
            Tuple of (status_code, response_text, json_data)
        """
        if not self.session:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))
        
        try:
            url = f"{self.rpc_url}{path}"
            async with getattr(self.session, method.lower())(url, json=data if method == 'POST' else None) as resp:
                text = await resp.text()
                try:
                    json_data = json.loads(text) if text else None
                except:
                    json_data = None
                return resp.status, text, json_data
        except asyncio.TimeoutError:
            return 0, "timeout", None
        except Exception as e:
            return 0, str(e), None
    
    async def get_status(self, force_refresh: bool = False) -> Tuple[Optional[int], Optional[float]]:
        """
        Get current nonce and balance.
        
        Args:
            force_refresh: Force refresh cache
            
        Returns:
            Tuple of (nonce, balance)
        """
        now = time.time()
        if not force_refresh and self.balance_cache is not None and (now - self.last_update) < 30:
            return self.nonce_cache, self.balance_cache
        
        # Get balance and staging transactions in parallel
        results = await asyncio.gather(
            self._request('GET', f'/balance/{self.address}'),
            self._request('GET', '/staging', 5),
            return_exceptions=True
        )
        
        status, text, json_data = results[0] if not isinstance(results[0], Exception) else (0, str(results[0]), None)
        staging_status, _, staging_data = results[1] if not isinstance(results[1], Exception) else (0, None, None)
        
        if status == 200 and json_data:
            self.nonce_cache = int(json_data.get('nonce', 0))
            self.balance_cache = float(json_data.get('balance', 0))
            self.last_update = now
            
            # Check for pending transactions to adjust nonce
            if staging_status == 200 and staging_data:
                our_txs = [tx for tx in staging_data.get('staged_transactions', []) if tx.get('from') == self.address]
                if our_txs:
                    self.nonce_cache = max(self.nonce_cache, max(int(tx.get('nonce', 0)) for tx in our_txs))
                    
        elif status == 404:
            self.nonce_cache, self.balance_cache, self.last_update = 0, 0.0, now
        elif status == 200 and text and not json_data:
            # Handle plain text response
            try:
                parts = text.strip().split()
                if len(parts) >= 2:
                    self.balance_cache = float(parts[0]) if parts[0].replace('.', '').isdigit() else 0.0
                    self.nonce_cache = int(parts[1]) if parts[1].isdigit() else 0
                    self.last_update = now
                else:
                    self.nonce_cache, self.balance_cache = None, None
            except:
                self.nonce_cache, self.balance_cache = None, None
        
        return self.nonce_cache, self.balance_cache
    
    async def get_history(self, limit: int = 20, force_refresh: bool = False) -> List[Dict]:
        """
        Get transaction history.
        
        Args:
            limit: Maximum number of transactions
            force_refresh: Force refresh cache
            
        Returns:
            List of transaction dictionaries
        """
        now = time.time()
        if not force_refresh and (now - self.last_history_update) < 60 and self.transaction_history:
            return self.transaction_history
        
        status, text, json_data = await self._request('GET', f'/address/{self.address}?limit={limit}')
        if status != 200 or (not json_data and not text):
            return self.transaction_history
        
        if json_data and 'recent_transactions' in json_data:
            tx_hashes = [ref["hash"] for ref in json_data.get('recent_transactions', [])]
            tx_results = await asyncio.gather(
                *[self._request('GET', f'/tx/{hash}', timeout=5) for hash in tx_hashes], 
                return_exceptions=True
            )
            
            existing_hashes = {tx['hash'] for tx in self.transaction_history}
            new_transactions = []
            
            for ref, result in zip(json_data.get('recent_transactions', []), tx_results):
                if isinstance(result, Exception):
                    continue
                    
                tx_status, _, tx_data = result
                if tx_status == 200 and tx_data and 'parsed_tx' in tx_data:
                    parsed = tx_data['parsed_tx']
                    tx_hash = ref['hash']
                    
                    if tx_hash in existing_hashes:
                        continue
                    
                    is_incoming = parsed.get('to') == self.address
                    amount_raw = parsed.get('amount_raw', parsed.get('amount', '0'))
                    amount = float(amount_raw) if '.' in str(amount_raw) else int(amount_raw) / self.MICROUNIT
                    
                    new_transactions.append({
                        'time': datetime.fromtimestamp(parsed.get('timestamp', 0)),
                        'hash': tx_hash,
                        'amount': amount,
                        'counterparty': parsed.get('to') if not is_incoming else parsed.get('from'),
                        'type': 'incoming' if is_incoming else 'outgoing',
                        'confirmed': True,
                        'nonce': parsed.get('nonce', 0),
                        'epoch': ref.get('epoch', 0)
                    })
            
            # Keep only recent transactions (last hour + new ones)
            cutoff_time = datetime.now() - timedelta(hours=1)
            self.transaction_history = sorted(
                new_transactions + [tx for tx in self.transaction_history if tx.get('time', datetime.now()) > cutoff_time],
                key=lambda x: x['time'], reverse=True
            )[:50]
            
            self.last_history_update = now
            
        elif status == 404 or (status == 200 and text and 'no transactions' in text.lower()):
            self.transaction_history.clear()
            self.last_history_update = now
        
        return self.transaction_history
    
    def _create_transaction(self, to_address: str, amount: float, nonce: int) -> Tuple[Dict, str]:
        """
        Create and sign a transaction.
        
        Args:
            to_address: Recipient address
            amount: Amount to send
            nonce: Transaction nonce
            
        Returns:
            Tuple of (transaction_dict, transaction_hash)
        """
        tx = {
            "from": self.address,
            "to_": to_address,
            "amount": str(int(amount * self.MICROUNIT)),
            "nonce": int(nonce),
            "ou": "1" if amount < 1000 else "3",
            "timestamp": time.time() + random.random() * 0.01
        }
        
        tx_bytes = json.dumps(tx, separators=(",", ":")).encode()
        signature = base64.b64encode(self.signing_key.sign(tx_bytes).signature).decode()
        
        tx.update({
            'signature': signature,
            'public_key': self.public_key
        })
        
        tx_hash = hashlib.sha256(tx_bytes).hexdigest()
        return tx, tx_hash
    
    async def send_transaction(self, to_address: str, amount: float) -> Dict[str, Any]:
        """
        Send a transaction.
        
        Args:
            to_address: Recipient address
            amount: Amount to send
            
        Returns:
            Dictionary with transaction result
        """
        # Validate inputs
        if not self.ADDRESS_PATTERN.match(to_address):
            raise OctraWalletError("Invalid recipient address")
        
        if not self.AMOUNT_PATTERN.match(str(amount)) or amount <= 0:
            raise OctraWalletError("Invalid amount")
        
        # Get current status
        nonce, balance = await self.get_status(force_refresh=True)
        
        if nonce is None:
            raise OctraWalletError("Failed to get current nonce")
        
        if not balance or balance < amount:
            raise OctraWalletError(f"Insufficient balance ({balance:.6f} < {amount})")
        
        # Create and send transaction
        tx, tx_hash = self._create_transaction(to_address, amount, nonce + 1)
        
        start_time = time.time()
        status, text, json_data = await self._request('POST', '/send-tx', tx)
        duration = time.time() - start_time
        
        if status == 200:
            if json_data and json_data.get('status') == 'accepted':
                result = {
                    'success': True,
                    'hash': json_data.get('tx_hash', tx_hash),
                    'duration': duration,
                    'pool_info': json_data.get('pool_info', {})
                }
            elif text.lower().startswith('ok'):
                result = {
                    'success': True,
                    'hash': text.split()[-1] if ' ' in text else tx_hash,
                    'duration': duration
                }
            else:
                result = {
                    'success': False,
                    'error': json_data if json_data else text,
                    'duration': duration
                }
        else:
            result = {
                'success': False,
                'error': json_data if json_data else text,
                'duration': duration
            }
        
        # Add to local history if successful
        if result['success']:
            self.transaction_history.append({
                'time': datetime.now(),
                'hash': result['hash'],
                'amount': amount,
                'counterparty': to_address,
                'type': 'outgoing',
                'confirmed': False  # Will be confirmed when we refresh history
            })
            # Reset cache to force refresh
            self.last_update = 0
        
        return result
    
    async def send_multiple_transactions(self, recipients: List[Tuple[str, float]], batch_size: int = 5) -> Dict[str, Any]:
        """
        Send multiple transactions.
        
        Args:
            recipients: List of (address, amount) tuples
            batch_size: Number of transactions to send in parallel
            
        Returns:
            Dictionary with batch results
        """
        if not recipients:
            raise OctraWalletError("No recipients provided")
        
        # Validate all recipients
        total_amount = 0
        for address, amount in recipients:
            if not self.ADDRESS_PATTERN.match(address):
                raise OctraWalletError(f"Invalid address: {address}")
            if not self.AMOUNT_PATTERN.match(str(amount)) or amount <= 0:
                raise OctraWalletError(f"Invalid amount: {amount}")
            total_amount += amount
        
        # Check balance
        nonce, balance = await self.get_status(force_refresh=True)
        if nonce is None:
            raise OctraWalletError("Failed to get current nonce")
        if not balance or balance < total_amount:
            raise OctraWalletError(f"Insufficient balance ({balance:.6f} < {total_amount})")
        
        # Process in batches
        batches = [recipients[i:i+batch_size] for i in range(0, len(recipients), batch_size)]
        successful_txs = []
        failed_txs = []
        
        for batch_idx, batch in enumerate(batches):
            tasks = []
            for i, (to_address, amount) in enumerate(batch):
                tx_nonce = nonce + 1 + (batch_idx * batch_size) + i
                tx, _ = self._create_transaction(to_address, amount, tx_nonce)
                tasks.append(self._send_single_tx(tx, to_address, amount))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for (to_address, amount), result in zip(batch, results):
                if isinstance(result, Exception):
                    failed_txs.append({
                        'address': to_address,
                        'amount': amount,
                        'error': str(result)
                    })
                elif result['success']:
                    successful_txs.append({
                        'address': to_address,
                        'amount': amount,
                        'hash': result['hash']
                    })
                    # Add to local history
                    self.transaction_history.append({
                        'time': datetime.now(),
                        'hash': result['hash'],
                        'amount': amount,
                        'counterparty': to_address,
                        'type': 'outgoing',
                        'confirmed': False
                    })
                else:
                    failed_txs.append({
                        'address': to_address,
                        'amount': amount,
                        'error': result['error']
                    })
        
        # Reset cache if any transactions succeeded
        if successful_txs:
            self.last_update = 0
        
        return {
            'successful': len(successful_txs),
            'failed': len(failed_txs),
            'total': len(recipients),
            'successful_transactions': successful_txs,
            'failed_transactions': failed_txs
        }
    
    async def _send_single_tx(self, tx: Dict, to_address: str, amount: float) -> Dict[str, Any]:
        """Send a single transaction (helper method)"""
        start_time = time.time()
        status, text, json_data = await self._request('POST', '/send-tx', tx)
        duration = time.time() - start_time
        
        if status == 200:
            if json_data and json_data.get('status') == 'accepted':
                return {
                    'success': True,
                    'hash': json_data.get('tx_hash', ''),
                    'duration': duration
                }
            elif text.lower().startswith('ok'):
                return {
                    'success': True,
                    'hash': text.split()[-1] if ' ' in text else '',
                    'duration': duration
                }
        
        return {
            'success': False,
            'error': json_data if json_data else text,
            'duration': duration
        }
    
    async def get_pending_transactions(self) -> List[Dict]:
        """
        Get pending transactions from staging pool.
        
        Returns:
            List of pending transaction dictionaries
        """
        status, _, json_data = await self._request('GET', '/staging', timeout=5)
        if status != 200 or not json_data:
            return []
        
        our_txs = [tx for tx in json_data.get('staged_transactions', []) if tx.get('from') == self.address]
        return our_txs
    
    def validate_address(self, address: str) -> bool:
        """
        Validate an Octra address.
        
        Args:
            address: Address to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        return bool(self.ADDRESS_PATTERN.match(address))
    
    def get_wallet_info(self) -> Dict[str, Any]:
        """
        Get wallet information.
        
        Returns:
            Dictionary with wallet details
        """
        return {
            'address': self.address,
            'public_key': self.public_key,
            'rpc_url': self.rpc_url,
            'has_private_key': bool(self.private_key)
        }
    
    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()


async def process_transaction(input_data: Dict) -> Dict:
    """
    Main entrypoint function that processes wallet operations based on input
    
    Args:
        input_data: Dictionary containing action and parameters
        
    Returns:
        Dictionary with operation results
    """
    try:
        wallet = OctraWallet(
            wallet_path=input_data.get('wallet_path', 'wallet.json')
        )
        
        action = input_data['action']
        
        if action == 'send':
            if not all(k in input_data for k in ['to_address', 'amount']):
                return {
                    'success': False,
                    'error': 'Missing required parameters: to_address and amount'
                }
            result = await wallet.send_transaction(
                input_data['to_address'],
                input_data['amount']
            )
            return {'success': True, 'data': result}
            
        elif action == 'status':
            status = await wallet.get_status()
            return {'success': True, 'data': {'block_height': status[0], 'balance': status[1]}}
            
        elif action == 'history':
            limit = input_data.get('limit', 20)
            history = await wallet.get_history(limit=limit)
            return {'success': True, 'data': {'transactions': history}}
            
        elif action == 'pending':
            pending = await wallet.get_pending_transactions()
            return {'success': True, 'data': {'pending_transactions': pending}}
            
        elif action == 'wallet_info':
            info = wallet.get_wallet_info()
            return {'success': True, 'data': info}
            
        else:
            return {'success': False, 'error': f'Unknown action: {action}'}
            
    except Exception as e:
        return {'success': False, 'error': str(e)}

# Example usage functions
async def example_usage():
    """Example usage of the Octra wallet module"""
    
    # Initialize wallet
    wallet = OctraWallet()
    
    try:
        # Load wallet
        wallet.load_wallet()
        print(f"Loaded wallet: {wallet.address}")
        
        # Get status
        nonce, balance = await wallet.get_status()
        print(f"Balance: {balance:.6f} OCT, Nonce: {nonce}")
        
        # Get transaction history
        history = await wallet.get_history()
        print(f"Transaction history: {len(history)} transactions")
        
        # Example single transaction (uncomment to use)
        # result = await wallet.send_transaction("oct1...", 1.0)
        # print(f"Transaction result: {result}")
        
        # Example multiple transactions (uncomment to use)
        # recipients = [("oct1...", 1.0), ("oct2...", 2.0)]
        # result = await wallet.send_multiple_transactions(recipients)
        # print(f"Batch result: {result}")
        
    except OctraWalletError as e:
        print(f"Wallet error: {e}")
    finally:
        await wallet.close()




if __name__ == "__main__":
    asyncio.run(example_usage())