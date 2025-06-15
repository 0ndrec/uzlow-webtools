"""Password generator tool for generating secure passwords with customizable parameters."""
import string
import secrets

# Schema definition for the tool
DATAFLOW_SCHEMA = {
    'name': 'Password Generator',
    'description': 'Generate secure passwords with customizable parameters',
    'entrypoint': 'generate_password',
    'input': {
        'length': {
            'type': 'integer',
            'description': 'Length of the password',
            'default': 12,
            'minimum': 8,
            'maximum': 128
        },
        'include_uppercase': {
            'type': 'boolean',
            'description': 'Include uppercase letters',
            'default': True
        },
        'include_lowercase': {
            'type': 'boolean',
            'description': 'Include lowercase letters',
            'default': True
        },
        'include_numbers': {
            'type': 'boolean',
            'description': 'Include numbers',
            'default': True
        },
        'include_special': {
            'type': 'boolean',
            'description': 'Include special characters',
            'default': True
        }
    }
}

def generate_password(params):
    """Generate a password based on the specified parameters.
    
    Args:
        params (dict): Dictionary containing password generation parameters
            - length: Length of the password
            - include_uppercase: Include uppercase letters
            - include_lowercase: Include lowercase letters
            - include_numbers: Include numbers
            - include_special: Include special characters
            
    Returns:
        dict: Dictionary containing the generated password
    """
    # Set default values if not provided
    length = params.get('length', 12)
    include_uppercase = params.get('include_uppercase', True)
    include_lowercase = params.get('include_lowercase', True)
    include_numbers = params.get('include_numbers', True)
    include_special = params.get('include_special', True)
    
    # Build character set based on parameters
    chars = ''
    if include_uppercase:
        chars += string.ascii_uppercase
    if include_lowercase:
        chars += string.ascii_lowercase
    if include_numbers:
        chars += string.digits
    if include_special:
        chars += string.punctuation
        
    if not chars:
        return {"error": "At least one character type must be selected"}
        
    # Generate password using secure random number generator
    try:
        password = ''.join(secrets.choice(chars) for _ in range(length))
        return {
            "password": password,
            "length": len(password),
            "contains_uppercase": any(c.isupper() for c in password),
            "contains_lowercase": any(c.islower() for c in password),
            "contains_numbers": any(c.isdigit() for c in password),
            "contains_special": any(c in string.punctuation for c in password)
        }
    except Exception as e:
        return {"error": str(e)}
