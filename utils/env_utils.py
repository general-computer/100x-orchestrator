import os
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class EnvManager:
    """Manages environment variables and .env files"""
    
    @staticmethod
    def find_env_file() -> Optional[Path]:
        """
        Look for .env file in standard locations:
        1. Home directory
        2. Git repo root
        3. Current directory
        """
        search_paths = [
            Path.home() / '.env',
            Path.cwd() / '.env',
        ]
        
        # Try to find git root
        try:
            import git
            repo = git.Repo(Path.cwd(), search_parent_directories=True)
            search_paths.insert(1, Path(repo.working_dir) / '.env')
        except Exception as e:
            logger.debug(f"Could not determine git root: {e}")
        
        for path in search_paths:
            if path.is_file():
                return path
                
        return None

    @staticmethod
    def load_env_file(env_path: Path) -> Dict[str, str]:
        """Load variables from .env file"""
        env_vars = {}
        
        try:
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        try:
                            key, value = line.split('=', 1)
                            env_vars[key.strip()] = value.strip()
                        except ValueError:
                            continue
        except Exception as e:
            logger.error(f"Error reading .env file: {e}")
            
        return env_vars

    @staticmethod
    def save_env_file(env_path: Path, env_vars: Dict[str, str]) -> bool:
        """Save variables to .env file"""
        try:
            # Read existing file to preserve comments and formatting
            existing_lines = []
            if env_path.exists():
                with open(env_path) as f:
                    existing_lines = f.readlines()

            # Update or add new variables
            updated_lines = []
            used_keys = set()

            for line in existing_lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        key = line.split('=', 1)[0].strip()
                        if key in env_vars:
                            updated_lines.append(f"{key}={env_vars[key]}\n")
                            used_keys.add(key)
                            continue
                    except ValueError:
                        pass
                updated_lines.append(line + '\n')

            # Add any new variables that weren't in the original file
            for key, value in env_vars.items():
                if key not in used_keys:
                    updated_lines.append(f"{key}={value}\n")

            # Write back to file
            with open(env_path, 'w') as f:
                f.writelines(updated_lines)

            return True
            
        except Exception as e:
            logger.error(f"Error saving .env file: {e}")
            return False

    @staticmethod
    def get_api_keys() -> Dict[str, str]:
        """Get all API keys from environment"""
        keys = {
            'openai_api_key': os.getenv('OPENAI_API_KEY', ''),
            'anthropic_api_key': os.getenv('ANTHROPIC_API_KEY', ''),
            'openrouter_api_key': os.getenv('OPENROUTER_API_KEY', '')
        }
        
        # Try loading from .env file if keys not in environment
        if not any(keys.values()):
            env_file = EnvManager.find_env_file()
            if env_file:
                env_vars = EnvManager.load_env_file(env_file)
                keys = {
                    'openai_api_key': env_vars.get('OPENAI_API_KEY', ''),
                    'anthropic_api_key': env_vars.get('ANTHROPIC_API_KEY', ''),
                    'openrouter_api_key': env_vars.get('OPENROUTER_API_KEY', '')
                }
                
        return keys

    @staticmethod
    def save_api_keys(keys: Dict[str, str]) -> bool:
        """Save API keys to .env file"""
        env_vars = {
            'OPENAI_API_KEY': keys.get('openai_api_key', ''),
            'ANTHROPIC_API_KEY': keys.get('anthropic_api_key', ''),
            'OPENROUTER_API_KEY': keys.get('openrouter_api_key', '')
        }
        
        # Find or create .env file
        env_file = EnvManager.find_env_file()
        if not env_file:
            env_file = Path.cwd() / '.env'
            
        return EnvManager.save_env_file(env_file, env_vars)
