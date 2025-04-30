# ipfs.py
import json
import os
import hashlib
import logging
import re
from cryptography.fernet import Fernet, InvalidToken
from datetime import datetime
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class IPFSManager:
    """Manages simulated IPFS storage with encryption."""

    def __init__(self, storage_dir='data/ipfs_storage', simulate=True):
        """Initializes the IPFS manager."""
        self.simulate = simulate # Note: Simulation is always active in this version
        self.storage_dir = storage_dir
        self.index_file = os.path.join(self.storage_dir, 'index.json')
        self.storage = {} # In-memory index

        try:
            os.makedirs(self.storage_dir, exist_ok=True)
            self._load_storage()
            logging.info(f"IPFSManager initialized. Simulation Mode: {self.simulate}. Storage: {self.storage_dir}")
        except OSError as e:
            logging.error(f"Failed to create storage directory {self.storage_dir}: {e}", exc_info=True)
            raise # Re-raise critical error
        except Exception as e:
            logging.error(f"Error during IPFSManager initialization: {e}", exc_info=True)
            # Allow continuing with an empty index if loading fails but dir exists
            self.storage = {}

    def _load_storage(self):
        """Loads the storage index from the index file."""
        try:
            if os.path.exists(self.index_file) and os.path.getsize(self.index_file) > 0:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    self.storage = json.load(f)
                logging.info(f"Loaded {len(self.storage)} entries from storage index.")
            else:
                self.storage = {}
                # Create the index file if it doesn't exist
                self._save_storage()
                logging.info("Initialized empty storage index.")
        except json.JSONDecodeError as e:
             logging.error(f"Error decoding index file {self.index_file}: {e}. Initializing empty index.", exc_info=True)
             self.storage = {}
        except Exception as e:
            logging.error(f"Failed to load storage index: {e}", exc_info=True)
            self.storage = {} # Fallback to empty index

    def _save_storage(self):
        """Saves the current storage index to the index file atomically."""
        temp_file = self.index_file + '.tmp'
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.storage, f, ensure_ascii=False, indent=4) # Use indent for readability
            # Atomic replace
            os.replace(temp_file, self.index_file)
            # logging.debug(f"Storage index saved successfully to {self.index_file}") # Optional: debug log
        except Exception as e:
            logging.error(f"Failed to save storage index: {e}", exc_info=True)
            # Attempt to remove potentially corrupted temp file
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    logging.error(f"Failed to remove temporary index file: {temp_file}")

    def _generate_hash(self, data):
        """Generates a SHA-256 hash for the given data."""
        try:
            # Ensure consistent serialization for hashing
            serialized = json.dumps(data, sort_keys=True, ensure_ascii=False).encode('utf-8')
            return hashlib.sha256(serialized).hexdigest()
        except TypeError as e:
            logging.error(f"Failed to serialize data for hashing: {e}")
            raise ValueError("Cannot hash unserializable data") from e

    def _generate_encryption_key(self):
        """Generates a new Fernet encryption key."""
        return Fernet.generate_key().decode('utf-8')

    def _encrypt_data(self, data, key):
        """Encrypts data using the provided Fernet key."""
        try:
            fernet = Fernet(key.encode('utf-8'))
            serialized = json.dumps(data, ensure_ascii=False).encode('utf-8')
            return fernet.encrypt(serialized)
        except Exception as e:
            logging.error(f"Encryption failed: {e}", exc_info=True)
            raise ValueError("Encryption process failed") from e

    def _decrypt_data(self, encrypted_data, key):
        """Decrypts data using the provided Fernet key."""
        try:
            fernet = Fernet(key.encode('utf-8'))
            decrypted_bytes = fernet.decrypt(encrypted_data)
            return json.loads(decrypted_bytes.decode('utf-8'))
        except InvalidToken:
            logging.error("Decryption failed: Invalid token or key.")
            raise ValueError("Decryption failed: Invalid token or key.")
        except Exception as e:
            logging.error(f"Decryption failed: {e}", exc_info=True)
            raise ValueError("Decryption process failed") from e

    def _validate_patient_name(self, name):
        """验证患者姓名是否有效"""
        if not isinstance(name, str):
            return False

        # 去除首尾空格
        name = name.strip()

        # 检查长度（2-50个字符）
        if len(name) < 2 or len(name) > 50:
            return False

        # 检查是否只包含允许的字符
        if not re.fullmatch(r'^[\u4e00-\u9fa5a-zA-Z\s\-·.\"]+$', name, re.UNICODE):
            return False

        # 检查是否包含至少一个非空格/标点字符
        if all(c in ' \-·.\"' for c in name):
            return False

        return True

    def validate_input(self, data):
        """Validates the input data structure for standard records."""
        if not isinstance(data, dict):
            return False, "Input data must be a dictionary."

        # Allow system markers (like deletion markers) or test data to bypass validation
        if data.get('action') == 'delete' or data.get('test') == "OK":
            return True, ""

        if 'patient_id' not in data or not str(data['patient_id']).strip():
            return False, "Missing or empty 'patient_id'."
        if 'patient_name' not in data or not str(data.get('patient_name',"")).strip():
            return False, "Missing or empty 'patient_name'."
        if not self._validate_patient_name(data.get('patient_name',"")):
             return False, f"Invalid 'patient_name': {data.get('patient_name','')}. Must be 2-50 valid characters."
        if 'record' not in data or not str(data['record']).strip():
            return False, "Missing or empty 'record' content."

        # Add other necessary field checks if needed

        return True, ""

    def hash_exists(self, ipfs_hash):
         """Checks if a hash exists in the index or file system."""
         if ipfs_hash in self.storage:
             return True
         # Check file system as fallback (in case index is out of sync)
         file_path = os.path.join(self.storage_dir, ipfs_hash)
         return os.path.exists(file_path)

    def store_data(self, data, tag='data'):
        """Stores encrypted data, updates index, and returns metadata."""
        # Validate input first
        is_valid, error_msg = self.validate_input(data)
        if not is_valid:
             logging.error(f"Invalid data for storage: {error_msg}. Data: {str(data)[:200]}...")
             raise ValueError(f"Invalid data for storage: {error_msg}")

        try:
            # Generate hash based on the data content itself
            ipfs_hash = self._generate_hash(data)

            # If hash already exists, return existing metadata (content-addressable)
            if ipfs_hash in self.storage:
                # Verify file exists for this hash as a sanity check
                if os.path.exists(os.path.join(self.storage_dir, ipfs_hash)):
                    logging.info(f"Data with hash {ipfs_hash[:8]}... already exists. Returning existing metadata.")
                    # Return a copy to prevent modification of internal state
                    return {**self.storage[ipfs_hash], 'ipfs_hash': ipfs_hash}
                else:
                    logging.warning(f"Hash {ipfs_hash[:8]}... found in index but file is missing. Proceeding to store.")
                    # Remove the inconsistent entry from storage before re-adding
                    del self.storage[ipfs_hash]


            # Generate new encryption key and encrypt data
            encryption_key = self._generate_encryption_key()
            encrypted_data = self._encrypt_data(data, encryption_key)

            # Assess data sensitivity
            sensitivity = self._assess_sensitivity(data)

            # Define metadata to store in the index
            metadata = {
                'tag': tag,
                'timestamp': datetime.now().isoformat(),
                'encryption_key': encryption_key,
                'sensitivity': sensitivity,
                'original_size': len(json.dumps(data, ensure_ascii=False).encode('utf-8')), # Store original size
                 'encrypted_size': len(encrypted_data) # Store encrypted size
            }

            # Write encrypted data to file named after its hash
            file_path = os.path.join(self.storage_dir, ipfs_hash)
            with open(file_path, 'wb') as f:
                f.write(encrypted_data)

            # Update the in-memory index and save it
            self.storage[ipfs_hash] = metadata
            self._save_storage()

            logging.info(f"Stored data with hash {ipfs_hash[:8]}... Tag: {tag}, Sensitivity: {sensitivity}")

            # Return metadata including the hash
            return {**metadata, 'ipfs_hash': ipfs_hash}

        except ValueError as ve: # Catch specific validation/hashing/encryption errors
             logging.error(f"Value error during data storage: {ve}", exc_info=True)
             raise # Re-raise validation errors
        except OSError as oe:
             logging.error(f"OS error during file write operation: {oe}", exc_info=True)
             # Attempt cleanup if file write failed partially? Maybe not safe.
             raise RuntimeError("Failed to write data file to storage") from oe
        except Exception as e:
            logging.error(f"Unexpected error during data storage: {e}", exc_info=True)
            # Attempt to remove the potentially bad index entry if it was added
            if 'ipfs_hash' in locals() and ipfs_hash in self.storage:
                 try:
                      del self.storage[ipfs_hash]
                      self._save_storage() # Try to save the corrected index
                 except Exception as save_err:
                      logging.error(f"Failed to rollback index update after storage error: {save_err}")
            raise RuntimeError("An unexpected error occurred during data storage") from e


    def retrieve_data(self, ipfs_hash, encryption_key):
        """Retrieves and decrypts data from storage."""
        if not ipfs_hash or not encryption_key:
             raise ValueError("IPFS hash and encryption key are required for retrieval.")

        file_path = os.path.join(self.storage_dir, ipfs_hash)

        # Check index first
        if ipfs_hash not in self.storage:
            # If not in index, check file system directly
            if not os.path.exists(file_path):
                 logging.error(f"Hash {ipfs_hash[:8]}... not found in index or file system.")
                 raise ValueError(f"Data record not found for hash: {ipfs_hash[:8]}...")
            else:
                 # File exists but not in index - potentially inconsistent state
                 logging.warning(f"Hash {ipfs_hash[:8]}... found in file system but not in index. Attempting retrieval.")
                 # Optionally, attempt to rebuild index here: self._rebuild_index()

        # Check if file exists (redundant if index check passed and consistent, but good safeguard)
        if not os.path.exists(file_path):
             logging.error(f"Data file missing for hash {ipfs_hash[:8]}... Index might be inconsistent.")
             # Attempt index rebuild or raise error
             # self._rebuild_index() # Potentially try to fix index
             raise ValueError(f"Data file not found for hash: {ipfs_hash[:8]}...")

        try:
            with open(file_path, 'rb') as f:
                encrypted_data = f.read()

            # Decrypt data
            decrypted_data = self._decrypt_data(encrypted_data, encryption_key)
            # logging.debug(f"Successfully retrieved and decrypted data for hash {ipfs_hash[:8]}...") # Optional debug log
            return decrypted_data

        except FileNotFoundError:
             # This case should ideally be caught by os.path.exists, but handle anyway
             logging.error(f"File not found during read operation for hash {ipfs_hash[:8]}...")
             raise ValueError(f"Data file disappeared unexpectedly for hash: {ipfs_hash[:8]}...")
        except ValueError as ve: # Catch decryption or key errors
             logging.error(f"Failed to retrieve/decrypt data for hash {ipfs_hash[:8]}... Error: {ve}", exc_info=True)
             raise # Re-raise specific decryption errors
        except Exception as e:
            logging.error(f"Unexpected error retrieving data for hash {ipfs_hash[:8]}... Error: {e}", exc_info=True)
            raise RuntimeError(f"Failed to retrieve data for hash {ipfs_hash[:8]}...") from e

    def _assess_sensitivity(self, data):
        """Assesses data sensitivity based on keywords."""
        # Simplified sensitivity check based on JSON string representation
        try:
            data_str = json.dumps(data, ensure_ascii=False).lower()
        except TypeError:
             data_str = str(data).lower() # Fallback for non-serializable data

        # Define keywords for different levels
        high_sens_kws = {'艾滋病', 'hiv', '性病', '梅毒', '淋病', '吸毒', '自杀', '暴力倾向'}
        med_sens_kws = {'遗传病', '先天缺陷', '精神分裂症', '抑郁症'} # Moved depression here

        if any(kw in data_str for kw in high_sens_kws):
            return 'high'
        # --- 修正点：将 'for med_sens_kws' 修改为 'for kw in med_sens_kws' ---
        if any(kw in data_str for kw in med_sens_kws):
            return 'medium'

        return 'low'

    def backup_storage(self, backup_root_dir='data/backups'):
        """Creates a timestamped backup of the entire storage directory."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = os.path.join(backup_root_dir, f"backup_{timestamp}")

        try:
            # Use shutil.copytree for a complete directory backup
            shutil.copytree(self.storage_dir, backup_dir, dirs_exist_ok=False) # Error if exists
            logging.info(f"Storage successfully backed up to: {backup_dir}")
            return backup_dir # Return the path to the backup
        except FileExistsError:
             logging.error(f"Backup directory {backup_dir} already exists. Backup aborted.")
             raise FileExistsError(f"Backup directory {backup_dir} already exists.")
        except Exception as e:
            logging.error(f"Storage backup failed: {e}", exc_info=True)
            # Attempt to clean up partially created backup directory if possible
            if os.path.exists(backup_dir):
                try:
                    shutil.rmtree(backup_dir)
                except Exception as cleanup_err:
                    logging.error(f"Failed to cleanup partial backup directory {backup_dir}: {cleanup_err}")
            raise RuntimeError("Storage backup operation failed") from e

    def restore_backup(self, backup_dir):
        """Restores storage from a specified backup directory."""
        # Basic validation of backup directory structure
        if not os.path.isdir(backup_dir):
             raise ValueError(f"Backup directory not found or is not a directory: {backup_dir}")
        backup_index_file = os.path.join(backup_dir, 'index.json')
        if not os.path.isfile(backup_index_file):
             raise ValueError(f"Backup directory {backup_dir} is missing the index.json file.")

        try:
            # 1. Clear current storage (ensure this is intended!)
            #    Consider requiring a specific confirmation or password here for safety.
            logging.warning("Clearing current storage before restoring from backup...")
            self._clear_storage_internal() # Use internal method without password check

            # 2. Copy backup files to storage directory
            #    We copy contents, not the directory itself, to the target storage_dir
            for item in os.listdir(backup_dir):
                 s = os.path.join(backup_dir, item)
                 d = os.path.join(self.storage_dir, item)
                 if os.path.isdir(s):
                      # Be careful with existing directories if any left after clear
                      shutil.copytree(s, d, dirs_exist_ok=True)
                 else:
                      shutil.copy2(s, d) # copy2 preserves metadata

            # 3. Reload the storage index from the restored index file
            self._load_storage()

            logging.info(f"Storage successfully restored from: {backup_dir}. Index reloaded with {len(self.storage)} entries.")
            return True

        except Exception as e:
            logging.error(f"Storage restoration from {backup_dir} failed: {e}", exc_info=True)
            # State might be inconsistent here. Manual check might be needed.
            raise RuntimeError(f"Storage restoration failed. System state might be inconsistent.") from e

    # Corrected Indentation
    def _clear_storage_internal(self):
        """Internal method to clear storage directory contents."""
        # Deletes files and subdirectories within the storage directory
        for filename in os.listdir(self.storage_dir):
            file_path = os.path.join(self.storage_dir, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                logging.error(f'Failed to delete {file_path}. Reason: {e}')
                # Decide if we should continue or stop on error
                raise RuntimeError(f"Failed to clear item {file_path} in storage.") from e
        # Reset in-memory index
        self.storage = {}
        # Recreate the empty index file
        self._save_storage()

    # Corrected Indentation
    def clear_storage(self, super_admin_password=None, confirm=False):
        """Clears the entire storage (requires password and confirmation)."""
        # Stronger check: Requires both password and explicit confirmation flag
        if super_admin_password != "admin.123":
            logging.error("Clear storage attempt failed: Incorrect super admin password.")
            raise PermissionError("Incorrect super admin password.")
        if not confirm:
            logging.warning("Clear storage attempt failed: Explicit confirmation required.")
            raise PermissionError("Clear storage requires explicit confirmation.")

        logging.warning("!!! Executing clear storage operation !!!")
        try:
            # Optional: Create a final backup before clearing
            # final_backup_path = self.backup_storage()
            # logging.info(f"Created final backup at {final_backup_path} before clearing.")

            self._clear_storage_internal()

            logging.warning("IPFS storage has been cleared successfully.")
            return True
        except Exception as e:
            logging.error(f"Clear storage operation failed: {e}", exc_info=True)
            # State might be inconsistent
            raise RuntimeError("Clear storage failed. Manual check recommended.") from e

    # Corrected Indentation
    def get_storage_stats(self):
        """Provides statistics about the stored data."""
        total_records = len(self.storage)
        total_encrypted_size = 0
        total_original_size = 0
        sensitivity_counts = {'high': 0, 'medium': 0, 'low': 0, 'unknown': 0}
        file_errors = 0

        for ipfs_hash, info in self.storage.items():
             file_path = os.path.join(self.storage_dir, ipfs_hash)
             try:
                 if os.path.exists(file_path):
                      # Use stored encrypted size if available, otherwise get file size
                      enc_size = info.get('encrypted_size', os.path.getsize(file_path))
                      total_encrypted_size += enc_size
                      total_original_size += info.get('original_size', 0) # Use stored original size
                 else:
                      logging.warning(f"File missing for indexed hash: {ipfs_hash[:8]}...")
                      file_errors += 1

                 sensitivity = info.get('sensitivity', 'unknown')
                 if sensitivity not in sensitivity_counts: sensitivity = 'unknown' # Handle unexpected values
                 sensitivity_counts[sensitivity] += 1

             except Exception as e:
                 logging.error(f"Error processing stats for hash {ipfs_hash[:8]}: {e}")
                 file_errors += 1


        return {
            'total_records': total_records,
            'total_encrypted_size_bytes': total_encrypted_size,
            'total_original_size_bytes': total_original_size, # Added original size stat
            'sensitivity_stats': sensitivity_counts,
            'file_consistency_errors': file_errors, # Added error count
            'last_update_time': datetime.now().isoformat() # More specific name
        }

    # Corrected Indentation
    def _rebuild_index(self):
         """(Optional) Attempts to rebuild the index from files in storage dir."""
         logging.warning("Attempting to rebuild IPFS storage index from file system...")
         rebuilt_index = {}
         files_found = 0
         errors = 0
         try:
              for filename in os.listdir(self.storage_dir):
                   file_path = os.path.join(self.storage_dir, filename)
                   # Basic check: is it a file and looks like a hash (64 hex chars)?
                   if os.path.isfile(file_path) and len(filename) == 64 and all(c in '0123456789abcdef' for c in filename):
                        files_found += 1
                        # Cannot reliably recover metadata (key, tag, etc.) without the original index
                        # We can only list the hashes found.
                        # For a true rebuild, metadata would need to be stored differently or inferred.
                        # This is a placeholder for a more complex recovery process.
                        # rebuilt_index[filename] = { 'status': 'found_file_only', 'timestamp': datetime.now().isoformat() }
                        logging.debug(f"Found potential data file: {filename}")
                   elif filename == 'index.json' or filename.endswith('.tmp'):
                        continue # Skip index files
                   else:
                        logging.warning(f"Skipping unexpected item during index rebuild: {filename}")

              # In a real scenario, you might compare this with the loaded index
              # For now, this function mostly serves as a diagnostic tool
              logging.info(f"Index rebuild scan complete. Found {files_found} potential data files.")
              # Decide whether to replace self.storage or merge, or just log.
              # self.storage = rebuilt_index # Example: Replace index (DANGEROUS without metadata)
              # self._save_storage()

         except Exception as e:
              logging.error(f"Error during index rebuild: {e}", exc_info=True)
              errors += 1
         return files_found, errors