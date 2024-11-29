import subprocess
import sys
import os
import logging

logger = logging.getLogger(__name__)

class AiderInstallationManager:
    @staticmethod
    def get_aider_path():
        """Get the full path to the aider executable"""
        if sys.platform == "win32":
            try:
                # First try running pip show to get the actual installation location
                pip_show = subprocess.check_output([
                    sys.executable, 
                    '-m', 
                    'pip', 
                    'show', 
                    'aider-chat'
                ], text=True)
                
                # Parse the location from pip show output
                location = None
                for line in pip_show.splitlines():
                    if line.startswith('Location:'):
                        location = line.split('Location:', 1)[1].strip()
                        break
                
                if location:
                    # Check multiple possible paths
                    possible_paths = [
                        os.path.join(location, '..', 'Scripts', 'aider.exe'),  # Regular install
                        os.path.join(location, 'Scripts', 'aider.exe'),        # User install
                        os.path.join(os.path.dirname(location), 'Scripts', 'aider.exe'),  # Alternative path
                        os.path.join(location, '..', '..', 'Scripts', 'aider.exe')  # Deep path
                    ]
                    
                    for path in possible_paths:
                        normalized_path = os.path.normpath(path)
                        logger.debug(f"Checking for aider at: {normalized_path}")
                        if os.path.exists(normalized_path):
                            logger.info(f"Found aider executable at: {normalized_path}")
                            return normalized_path
                
                # Fallback to checking PATH
                paths = os.environ.get('PATH', '').split(os.pathsep)
                for path in paths:
                    aider_path = os.path.join(path, 'aider.exe')
                    if os.path.exists(aider_path):
                        logger.info(f"Found aider in PATH at: {aider_path}")
                        return aider_path
                        
                logger.warning("Could not find aider.exe in any expected location")
                return None
                
            except subprocess.CalledProcessError as e:
                logger.error(f"Error checking pip installation: {e}")
                return None
                
            except Exception as e:
                logger.error(f"Unexpected error locating aider: {e}")
                return None
        else:
            # For non-Windows systems
            try:
                path = subprocess.check_output(['which', 'aider'], text=True).strip()
                logger.info(f"Found aider at: {path}")
                return path
            except subprocess.CalledProcessError:
                logger.warning("Could not find aider in PATH")
                return None

    @staticmethod
    def check_pip_installation():
        """Check if pip is installed"""
        try:
            subprocess.check_output([sys.executable, '-m', 'pip', '--version'])
            return True
        except subprocess.CalledProcessError:
            return False

    @staticmethod
    def install_aider():
        """Install aider package using pip"""
        try:
            logger.info("Attempting to install aider-chat...")
            subprocess.check_call([
                sys.executable, 
                '-m', 
                'pip', 
                'install', 
                'aider-chat',
                '--user'  # Install for current user only
            ])
            logger.info("Successfully installed aider-chat")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install aider-chat: {str(e)}")
            return False

    @staticmethod
    def check_aider_installation():
        """Verify aider installation and attempt installation if missing"""
        try:
            # First check if the package is installed via pip
            try:
                subprocess.check_output([
                    sys.executable, 
                    '-m', 
                    'pip', 
                    'show', 
                    'aider-chat'
                ], text=True)
                logger.info("aider-chat package is installed")
                
                # Now verify we can run it
                aider_path = AiderInstallationManager.get_aider_path()
                if aider_path and os.path.exists(aider_path):
                    logger.info(f"Found aider at: {aider_path}")
                    try:
                        # Try running aider
                        result = subprocess.run(
                            [aider_path, '--version'], 
                            capture_output=True, 
                            text=True,
                            env=dict(os.environ, PYTHONIOENCODING='utf-8')
                        )
                        if result.returncode == 0:
                            logger.info("Aider is installed and working")
                            return True, None
                    except subprocess.CalledProcessError:
                        logger.warning("Aider found but not working properly")
                
                logger.warning("Aider package installed but executable not found")
                
            except subprocess.CalledProcessError:
                logger.warning("Aider package not installed")
            
            logger.warning("Attempting installation...")
            
            # Verify pip is available
            if not AiderInstallationManager.check_pip_installation():
                error_msg = "pip is not installed. Please install pip first."
                logger.error(error_msg)
                return False, error_msg
            
            # Attempt to install aider
            if AiderInstallationManager.install_aider():
                # Try to find aider again after installation
                aider_path = AiderInstallationManager.get_aider_path()
                if aider_path and os.path.exists(aider_path):
                    try:
                        # Verify the installation works
                        subprocess.run(
                            [aider_path, '--version'], 
                            check=True, 
                            capture_output=True,
                            env=dict(os.environ, PYTHONIOENCODING='utf-8')
                        )
                        logger.info("Aider installation verified successfully")
                        return True, None
                    except subprocess.CalledProcessError as e:
                        error_msg = f"Aider installation completed but verification failed: {str(e)}"
                        logger.error(error_msg)
                        return False, error_msg
                else:
                    error_msg = "Aider installed but executable not found in expected location"
                    logger.error(error_msg)
                    return False, error_msg
            else:
                error_msg = "Failed to install aider-chat. Please install manually using: pip install aider-chat"
                logger.error(error_msg)
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Unexpected error checking/installing aider: {str(e)}"
            logger.error(error_msg)
            return False, error_msg

    @staticmethod
    def get_aider_command():
        """Get the full command to run aider"""
        aider_path = AiderInstallationManager.get_aider_path()
        if aider_path:
            return aider_path
        return 'aider'
