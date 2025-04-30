# blockchain.py
import os
import json
import hashlib
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define constants for file paths
DATA_DIR = 'data'
BLOCKCHAIN_FILE = os.path.join(DATA_DIR, 'blockchain.jsonl')
AUDIT_LOG_FILE = os.path.join(DATA_DIR, 'blockchain_audit.jsonl')

class MedicalBlockchain:
    """
    Manages the medical record blockchain using JSON Lines format.
    Focuses on immutability by adding new blocks for updates/deletions.
    """
    def __init__(self, ipfs_manager):
        """Initializes the blockchain."""
        if not hasattr(ipfs_manager, 'store_data') or not hasattr(ipfs_manager, 'retrieve_data'):
             raise TypeError("ipfs_manager must provide store_data and retrieve_data methods")

        self.ipfs = ipfs_manager
        self.chain = [] # In-memory representation of the chain
        self.block_index = {} # Index for quick block lookup by ID: {block_id: block_data}
        self.patient_name_cache = {} # Cache for patient ID -> Name consistency {patient_id: name}

        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            self._load_chain()
            self._init_audit_log()
            logging.info(f"MedicalBlockchain initialized. Chain length: {len(self.chain)}")
        except Exception as e:
            logging.error(f"Failed to initialize MedicalBlockchain: {e}", exc_info=True)
            # Depending on severity, might need to halt or continue with empty chain
            self.chain = []
            self.block_index = {}
            # Consider creating genesis block if chain is empty after load failure
            if not self.chain:
                 self._create_genesis_block()


    def _create_genesis_block(self):
        """Creates the initial block in the chain if it's empty."""
        if not self.chain:
            genesis_block = {
                'block_id': 0,
                'timestamp': datetime.now().isoformat(),
                'transaction_type': 'GENESIS',
                'patient_id': 'SYSTEM',
                'ipfs_hash': '0' * 64, # No data for genesis
                'metadata': {'description': 'Genesis Block'},
                'prev_hash': '0' * 64,
                'block_hash': self._hash_block_content({ # Hash the content
                     'block_id': 0,
                     'timestamp': datetime.now().isoformat(), # Use consistent timestamp if needed
                     'transaction_type': 'GENESIS',
                     'patient_id': 'SYSTEM',
                     'ipfs_hash': '0' * 64,
                     'metadata': {'description': 'Genesis Block'},
                     'prev_hash': '0' * 64
                }),
                'status': 'ACTIVE' # Status: ACTIVE, SUPERSEDED, DELETED
            }
            self.chain.append(genesis_block)
            self.block_index[0] = genesis_block
            self._append_to_file(BLOCKCHAIN_FILE, genesis_block)
            logging.info("Created Genesis Block.")

    def _load_chain(self):
        """Loads the blockchain from the JSON Lines file."""
        self.chain = []
        self.block_index = {}
        self.patient_name_cache = {}
        try:
            if os.path.exists(BLOCKCHAIN_FILE):
                with open(BLOCKCHAIN_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                block = json.loads(line)
                                self.chain.append(block)
                                if 'block_id' in block:
                                     self.block_index[block['block_id']] = block
                                # Update patient name cache during load
                                if block.get('transaction_type') == 'CREATE' and block.get('status') == 'ACTIVE':
                                     pid = block.get('patient_id')
                                     pname = block.get('metadata', {}).get('patient_name')
                                     if pid and pname:
                                          # Only cache the latest active name
                                          self.patient_name_cache[pid] = pname

                            except json.JSONDecodeError as jde:
                                logging.error(f"Skipping corrupted line in blockchain file: {line.strip()} - Error: {jde}")
                                continue # Skip corrupted lines

            if not self.chain:
                 self._create_genesis_block()
            elif not self._validate_chain_integrity():
                 # Decide on action: halt, try repair, log error...
                 logging.critical("Blockchain integrity validation failed upon loading!")
                 # raise RuntimeError("Blockchain corrupted. Manual intervention required.")
            else:
                 logging.info(f"Blockchain loaded successfully. Length: {len(self.chain)}")


        except FileNotFoundError:
            logging.info(f"Blockchain file {BLOCKCHAIN_FILE} not found. Creating Genesis block.")
            self._create_genesis_block()
        except Exception as e:
            logging.error(f"Failed to load blockchain: {e}", exc_info=True)
            # Reset state if load fails critically
            self.chain = []
            self.block_index = {}
            self._create_genesis_block() # Ensure genesis exists even after failure


    def _append_to_file(self, file_path, data):
        """Appends a JSON object as a new line to the specified file."""
        try:
            # Append mode ensures we add to the end
            with open(file_path, 'a', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
                f.write('\n') # Add newline separator
            # Successful write
            return True
        except Exception as e:
            logging.error(f"Failed to append to file {file_path}: {e}", exc_info=True)
            # This is critical, might need to signal failure
            raise IOError(f"Failed to write to blockchain/log file: {file_path}") from e

    def _init_audit_log(self):
        """ Initializes the audit log file if it doesn't exist. """
        if not os.path.exists(AUDIT_LOG_FILE):
            try:
                # Create the file, potentially add headers if using CSV later
                 with open(AUDIT_LOG_FILE, 'w', encoding='utf-8') as f:
                      # Example header (optional, as each line is JSON)
                      # header = {'timestamp': 'ISOFormat', 'action': '', 'details': {}}
                      # json.dump(header, f, ensure_ascii=False)
                      # f.write('\n')
                      pass # Just create the file
                 logging.info(f"Audit log file initialized: {AUDIT_LOG_FILE}")
            except Exception as e:
                 logging.error(f"Failed to initialize audit log file: {e}", exc_info=True)


    def _log_audit(self, action, details):
        """Logs an action to the audit log file."""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'action': action,
            'details': details
        }
        # Use the _append_to_file method to ensure consistent error handling
        try:
            self._append_to_file(AUDIT_LOG_FILE, log_entry)
            logging.debug("Audit entry written successfully.") # Debug level for frequent logs
        except IOError as e:
            logging.error(f"Failed to write audit log entry: {e}", exc_info=True)
            # Decide if audit log failure is critical. For now, we log the failure but don't stop the main process.


    def _hash_block_content(self, block_content):
        """Hashes the content of a block (excluding the block_hash itself)."""
        # Ensure consistent ordering and encoding for hashing
        try:
             # Create a copy to avoid modifying the original dict
             content_to_hash = block_content.copy()
             # Exclude the hash field itself if present (shouldn't be during creation)
             content_to_hash.pop('block_hash', None)

             serialized = json.dumps(content_to_hash, sort_keys=True, ensure_ascii=False).encode('utf-8')
             return hashlib.sha256(serialized).hexdigest()
        except Exception as e:
             logging.error(f"Failed to hash block content: {e}", exc_info=True)
             raise ValueError("Could not hash block content") from e


    def get_last_block(self):
        """Returns the last block in the chain."""
        return self.chain[-1] if self.chain else None

    def _validate_chain_integrity(self):
         """Validates the hashes and links in the loaded chain."""
         if len(self.chain) <= 1: # Genesis only or empty
              return True

         for i in range(1, len(self.chain)):
              current_block = self.chain[i]
              prev_block = self.chain[i-1]

              # 1. Validate previous hash link
              if current_block.get('prev_hash') != prev_block.get('block_hash'):
                   logging.error(f"Chain integrity error: Block {current_block.get('block_id')} prev_hash mismatch.")
                   return False

              # 2. Validate current block's content hash
              # Recompute hash based on content *excluding* the stored block_hash
              block_content_for_hash = current_block.copy()
              block_content_for_hash.pop('block_hash', None) # Remove hash before recomputing
              expected_hash = self._hash_block_content(block_content_for_hash)

              if current_block.get('block_hash') != expected_hash:
                   logging.error(f"Chain integrity error: Block {current_block.get('block_id')} content hash mismatch.")
                   # Log details for debugging
                   logging.debug(f"Expected hash: {expected_hash}")
                   logging.debug(f"Actual hash:   {current_block.get('block_hash')}")
                   # logging.debug(f"Block Content: {json.dumps(current_block, sort_keys=True, indent=2)}") # Be careful logging sensitive data
                   return False

         logging.info("Blockchain integrity validation successful.")
         return True


    def _verify_patient_name_consistency(self, patient_id, expected_name):
         """Checks if the provided name matches the cached name for the patient ID."""
         cached_name = self.patient_name_cache.get(patient_id)
         if cached_name is None:
              # Name not cached, this might be the first record for this patient
              return True
         elif cached_name == expected_name:
              return True
         else:
              logging.warning(f"Patient name inconsistency detected for ID {patient_id}. Expected: {expected_name}, Found in Cache: {cached_name}")
              return False

    def add_record(self, patient_id, patient_name, record_data):
        """Adds a new medical record to the blockchain."""
        logging.info(f"Attempting to add new record for patient ID: {patient_id}")
        if not patient_id or not patient_name or not record_data:
            logging.error("Add record failed: Patient ID, Name, and Record Data are required.")
            raise ValueError("Patient ID, Name, and Record Data are required.")

        # Verify name consistency before storing data
        if not self._verify_patient_name_consistency(patient_id, patient_name):
             raise ValueError(f"Patient name mismatch for ID {patient_id}. Cannot add record.")

        try:
            # 1. Store the actual medical record data in IPFS
            logging.info(f"Storing new record data in IPFS for patient {patient_id}...")
            #    Combine necessary info for IPFS storage
            ipfs_payload = {
                'patient_id': patient_id,
                'patient_name': patient_name,
                **record_data # Includes 'record', 'diagnosis', 'ai_analysis', etc.
            }
            ipfs_result = self.ipfs.store_data(ipfs_payload, tag='medical_record')
            logging.info(f"New record data stored in IPFS. Hash: {ipfs_result['ipfs_hash'][:12]}...")

            # 2. Prepare the new block content
            last_block = self.get_last_block()
            # Calculate new block ID - handle empty chain case
            new_block_id = last_block['block_id'] + 1 if last_block else 0
            timestamp = datetime.now().isoformat()
            logging.info(f"Preparing new CREATE block {new_block_id}...")

            block_content = {
                'block_id': new_block_id,
                'timestamp': timestamp,
                'transaction_type': 'CREATE', # Type of transaction
                'patient_id': patient_id,
                'ipfs_hash': ipfs_result['ipfs_hash'], # Hash of data in IPFS
                'metadata': { # Store non-sensitive metadata directly
                    'patient_name': patient_name, # Store name for easier lookup/validation
                    'encryption_key': ipfs_result['encryption_key'],
                    'sensitivity': ipfs_result['sensitivity'],
                    'original_size': ipfs_result.get('original_size'),
                    'encrypted_size': ipfs_result.get('encrypted_size')
                },
                'prev_hash': last_block['block_hash'] if last_block else '0'*64,
                'status': 'ACTIVE' # Initial status
            }

            # 3. Hash the block content to get the block_hash
            block_hash = self._hash_block_content(block_content)
            block_content['block_hash'] = block_hash # Add the hash to the final block
            logging.info(f"CREATE block {new_block_id} prepared. Hash: {block_hash[:12]}...")


            # 4. Append block to chain file FIRST
            logging.info(f"Appending CREATE block {new_block_id} to chain file...")
            try:
                self._append_to_file(BLOCKCHAIN_FILE, block_content)
                logging.info(f"CREATE block {new_block_id} successfully appended to chain file.")
            except IOError as ioe:
                 logging.error(f"Failed to write CREATE block {new_block_id} to blockchain file: {ioe}", exc_info=True)
                 # File write failed, do NOT update in-memory state
                 raise RuntimeError("Failed to save new block to persistent storage.") from ioe

            # 5. If file write succeeded, update in-memory chain and index
            self.chain.append(block_content)
            self.block_index[new_block_id] = block_content
            logging.info(f"In-memory chain updated with new block {new_block_id}.")


             # Update patient name cache only if this is the first record or name matches
            if patient_id not in self.patient_name_cache:
                 self.patient_name_cache[patient_id] = patient_name
                 logging.info(f"Patient name '{patient_name}' cached for ID '{patient_id}'.")


            # 6. Log the audit trail (could fail independently)
            logging.info(f"Logging audit trail for ADD_RECORD operation (Block: {new_block_id})...")
            try:
                self._log_audit('ADD_RECORD', {
                    'block_id': new_block_id,
                    'patient_id': patient_id,
                    'ipfs_hash': ipfs_result['ipfs_hash'],
                    'user': 'System/App' # Indicate source if user not tracked here
                })
                logging.info("Audit trail logged successfully.")
            except IOError as ioe:
                logging.error(f"Failed to write audit log for ADD_RECORD operation: {ioe}", exc_info=True)
                pass # Do not re-raise, let record addition succeed even if audit fails


            logging.info(f"Add record process completed successfully for patient {patient_id} (Block: {new_block_id}).")
            return block_content # Return the created block

        except ValueError as ve:
            logging.error(f"Add record failed: {ve}", exc_info=True)
            raise # Re-raise specific validation errors
        except RuntimeError as rte: # Catch runtime errors from IPFS or _append_to_file
             logging.error(f"Add record runtime error: {rte}", exc_info=True)
             raise
        except Exception as e:
            logging.error(f"Unexpected error adding record: {e}", exc_info=True)
            raise RuntimeError("An unexpected error occurred while adding the record.") from e

    def update_record_content(self, original_block_id, new_record_data, user, reason):
        """Updates a record by adding a new 'UPDATE' block."""
        logging.info(f"Attempting to update record for block ID: {original_block_id} by user: {user}")
        if not user or not reason:
             logging.error("Update record failed: User and reason are required.")
             raise ValueError("User and reason are required for updating a record.")

        # 1. Find the original block
        original_block = self.get_block(original_block_id)
        if not original_block:
            logging.error(f"Update record failed: Original block with ID {original_block_id} not found.")
            raise ValueError(f"Original block with ID {original_block_id} not found.")

        # Use dynamic status check to ensure we modify the truly latest active block
        current_status = self.get_block_status(original_block_id)
        if current_status != 'ACTIVE':
             logging.error(f"Update record failed: Cannot update block {original_block_id} which is not ACTIVE (Current Status: {current_status}).")
             raise ValueError(f"Cannot update block {original_block_id} which is not ACTIVE (Current Status: {current_status}).")


        patient_id = original_block['patient_id']
        original_ipfs_hash = original_block['ipfs_hash']
        original_metadata = original_block.get('metadata', {})
        patient_name = original_metadata.get('patient_name', "Unknown") # Get name from original block's metadata
        logging.info(f"Found active block {original_block_id} for patient {patient_id}. Proceeding with update.")

        try:
            # 2. Store the *new* record data in IPFS
            logging.info(f"Storing new record data in IPFS for patient {patient_id}...")
            new_ipfs_payload = {
                'patient_id': patient_id,
                'patient_name': patient_name, # Carry over original patient name
                **new_record_data # The updated content
            }
            # Assuming store_data has internal logging for success/failure
            new_ipfs_result = self.ipfs.store_data(new_ipfs_payload, tag='medical_record_update')
            logging.info(f"New record data stored in IPFS. Hash: {new_ipfs_result['ipfs_hash'][:12]}...")

            # 3. Prepare the 'UPDATE' transaction block
            last_block = self.get_last_block()
            # Calculate new block ID - handle empty chain case
            new_block_id = last_block['block_id'] + 1 if last_block else 0
            timestamp = datetime.now().isoformat()
            logging.info(f"Preparing new UPDATE block {new_block_id}...")

            update_block_content = {
                'block_id': new_block_id,
                'timestamp': timestamp,
                'transaction_type': 'UPDATE',
                'patient_id': patient_id,
                'ipfs_hash': new_ipfs_result['ipfs_hash'], # Hash of the *new* data
                'metadata': {
                    'patient_name': patient_name,
                    'encryption_key': new_ipfs_result['encryption_key'],
                    'sensitivity': new_ipfs_result['sensitivity'],
                    'original_size': new_ipfs_result.get('original_size'),
                    'encrypted_size': new_ipfs_result.get('encrypted_size'),
                    'updated_by': user,
                    'update_reason': reason,
                    'supersedes_block': original_block_id, # Link to the block being updated
                    'original_ipfs_hash': original_ipfs_hash # Reference the old IPFS hash
                },
                'prev_hash': last_block['block_hash'],
                'status': 'ACTIVE' # The update block is the new active one
            }
            block_hash = self._hash_block_content(update_block_content)
            update_block_content['block_hash'] = block_hash
            logging.info(f"UPDATE block {new_block_id} prepared. Hash: {block_hash[:12]}...")

            # 4. Append block to chain file FIRST
            logging.info(f"Appending UPDATE block {new_block_id} to chain file...")
            try:
                 self._append_to_file(BLOCKCHAIN_FILE, update_block_content)
                 logging.info(f"UPDATE block {new_block_id} successfully appended to chain file.")
            except IOError as ioe:
                 logging.error(f"Failed to write UPDATE block {new_block_id} to blockchain file: {ioe}", exc_info=True)
                 # File write failed, do NOT update in-memory state for the new block or original block
                 raise RuntimeError("Failed to save update block to persistent storage.") from ioe

            # 5. If file write succeeded, update in-memory chain and index for the NEW block
            self.chain.append(update_block_content)
            self.block_index[new_block_id] = update_block_content
            logging.info(f"In-memory chain updated with new block {new_block_id}.")

            # 6. Mark the original block as 'SUPERSEDED' in memory index ONLY AFTER new block is saved
            #    Note: The file blockchain.jsonl still contains the old status field value.
            #    Status is determined dynamically by get_block_status, but updating memory helps index consistency.
            logging.info(f"Marking original block {original_block_id} as SUPERSEDED in memory index.")
            # Need to check if original_block_id exists in index *before* updating its status
            if original_block_id in self.block_index:
                 # Create a copy before modifying to avoid issues if this block is still referenced elsewhere
                 original_block_in_memory = self.block_index[original_block_id]
                 if 'status' in original_block_in_memory:
                      original_block_in_memory['status'] = 'SUPERSEDED'
                 else:
                      # If status wasn't there, add it
                      original_block_in_memory['status'] = 'SUPERSEDED'
                 logging.debug(f"In-memory status for block {original_block_id} updated to SUPERSEDED.")
            else:
                 logging.warning(f"Original block {original_block_id} not found in in-memory index when trying to update status.")


            # 7. Log the audit trail (this also appends to file, could fail independently)
            logging.info(f"Logging audit trail for UPDATE operation (New Block: {new_block_id}, Original: {original_block_id})...")
            try:
                 self._log_audit('UPDATE_RECORD', {
                     'new_block_id': new_block_id,
                     'superseded_block_id': original_block_id,
                     'patient_id': patient_id,
                     'user': user,
                     'reason': reason,
                     'new_ipfs_hash': new_ipfs_result['ipfs_hash']
                 })
                 logging.info("Audit trail logged successfully.")
            except IOError as ioe:
                 logging.error(f"Failed to write audit log for UPDATE operation: {ioe}", exc_info=True)
                 # Decide criticality - we'll let update succeed but log audit failure
                 # Consider raising a warning to the user or specific error type
                 pass # Do not re-raise, let update succeed if audit fails


            logging.info(f"Update process completed successfully for block {original_block_id} (New Block: {new_block_id}).")
            return update_block_content # Return the created update block

        except ValueError as ve:
            logging.error(f"Value error during record update: {ve}", exc_info=True)
            raise # Re-raise specific validation errors
        except RuntimeError as rte: # Catch runtime errors from IPFS or _append_to_file
             logging.error(f"Runtime error during record update: {rte}", exc_info=True)
             # Re-raise specific runtime errors (e.g. from IPFS or file write)
             raise
        except Exception as e:
            logging.error(f"Unexpected error during record update: {e}", exc_info=True)
            # Re-raise as a generic runtime error for app.py to catch
            raise RuntimeError("An unexpected error occurred while updating the record.") from e

    def delete_record(self, block_id_to_delete, user, reason):
        """Deletes a record by adding a 'DELETE' marker block."""
        logging.info(f"Attempting to delete record block ID: {block_id_to_delete} by user: {user}")
        if not user or not reason:
            raise ValueError("User and reason are required for deleting a record.")

        # 1. Find the block to delete
        target_block = self.get_block(block_id_to_delete)
        if not target_block:
            logging.error(f"Delete record failed: Block with ID {block_id_to_delete} not found.")
            raise ValueError(f"Block with ID {block_id_to_delete} not found.")

        # Use dynamic status check to ensure we delete the truly latest active block
        current_status = self.get_block_status(block_id_to_delete) # Use dynamic status check
        if current_status != 'ACTIVE':
             logging.error(f"Delete record failed: Cannot delete block {block_id_to_delete} which is not ACTIVE (Current Status: {current_status}).")
             raise ValueError(f"Cannot delete block {block_id_to_delete} which is not ACTIVE (Current Status: {current_status}).")

        patient_id = target_block['patient_id']
        target_ipfs_hash = target_block['ipfs_hash']
        patient_name = target_block.get('metadata', {}).get('patient_name', "Unknown")
        logging.info(f"Found active block {block_id_to_delete} for patient {patient_id}. Proceeding with deletion marker.")


        try:
            # 2. Prepare the 'DELETE' transaction block
            last_block = self.get_last_block()
            # Calculate new block ID - handle empty chain case
            new_block_id = last_block['block_id'] + 1 if last_block else 0
            timestamp = datetime.now().isoformat()
            logging.info(f"Preparing new DELETE block {new_block_id}...")


            delete_block_content = {
                'block_id': new_block_id,
                'timestamp': timestamp,
                'transaction_type': 'DELETE',
                'patient_id': patient_id, # Record patient ID for context
                'ipfs_hash': '0' * 64, # No new data stored in IPFS for deletion marker
                'metadata': {
                    'patient_name': patient_name, # Record patient name
                    'deleted_by': user,
                    'delete_reason': reason,
                    'deleted_block_id': block_id_to_delete, # Link to the block being deleted
                    'deleted_ipfs_hash': target_ipfs_hash # Reference the deleted data hash
                },
                'prev_hash': last_block['block_hash'],
                'status': 'MARKER' # Special status for deletion markers
            }
            block_hash = self._hash_block_content(delete_block_content)
            delete_block_content['block_hash'] = block_hash
            logging.info(f"DELETE block {new_block_id} prepared. Hash: {block_hash[:12]}...")


            # 3. Add the delete marker block to the chain file FIRST
            logging.info(f"Appending DELETE block {new_block_id} to chain file...")
            try:
                self._append_to_file(BLOCKCHAIN_FILE, delete_block_content)
                logging.info(f"DELETE block {new_block_id} successfully appended to chain file.")
            except IOError as ioe:
                 logging.error(f"Failed to write DELETE block {new_block_id} to blockchain file: {ioe}", exc_info=True)
                 # File write failed, do NOT update in-memory state
                 raise RuntimeError("Failed to save delete marker block to persistent storage.") from ioe

            # 4. If file write succeeded, Add the delete marker block to in-memory chain and index
            self.chain.append(delete_block_content)
            self.block_index[new_block_id] = delete_block_content
            logging.info(f"In-memory chain updated with new block {new_block_id}.")


            # 5. Update the status of the target block in memory ONLY AFTER marker block is saved
            #    Note: The file blockchain.jsonl still contains the old status field value.
            #    Relies on dynamic status checking during retrieval (get_block_status).
            logging.info(f"Marking original block {block_id_to_delete} as DELETED in memory index.")
            if block_id_to_delete in self.block_index:
                 # Create a copy before modifying
                 original_block_in_memory = self.block_index[block_id_to_delete]
                 if 'status' in original_block_in_memory:
                      original_block_in_memory['status'] = 'DELETED'
                 else:
                      original_block_in_memory['status'] = 'DELETED'
                 logging.debug(f"In-memory status for block {block_id_to_delete} updated to DELETED.")
            else:
                 logging.warning(f"Target block {block_id_to_delete} not found in in-memory index when trying to update status.")


            # 6. Log the audit trail (could fail independently)
            logging.info(f"Logging audit trail for DELETE operation (Marker Block: {new_block_id}, Deleted: {block_id_to_delete})...")
            try:
                 self._log_audit('DELETE_RECORD', {
                     'marker_block_id': new_block_id,
                     'deleted_block_id': block_id_to_delete,
                     'patient_id': patient_id,
                     'user': user,
                     'reason': reason,
                     'original_ipfs_hash': target_ipfs_hash # Include original hash in audit
                 })
                 logging.info("Audit trail logged successfully.")
            except IOError as ioe:
                 logging.error(f"Failed to write audit log for DELETE operation: {ioe}", exc_info=True)
                 pass # Do not re-raise


            logging.info(f"Delete marker process completed successfully for block {block_id_to_delete} (Marker Block: {new_block_id}).")
            return delete_block_content

        except ValueError as ve:
            logging.error(f"Delete record failed: {ve}", exc_info=True)
            raise
        except RuntimeError as rte: # Catch runtime errors from IPFS or _append_to_file
             logging.error(f"Runtime error during record delete: {rte}", exc_info=True)
             raise
        except Exception as e:
            logging.error(f"Unexpected error deleting record: {e}", exc_info=True)
            raise RuntimeError("An unexpected error occurred while deleting the record.") from e


    def get_block(self, block_id):
        """Retrieves a block by its ID from the in-memory index."""
        # Ensure block_id is an integer
        try:
             block_id = int(block_id)
        except (ValueError, TypeError):
             logging.warning(f"Invalid block_id type received: {block_id}")
             return None
        return self.block_index.get(block_id) # Use index for O(1) lookup

    def get_block_status(self, block_id):
         """Determines the current status (ACTIVE, SUPERSEDED, DELETED) of a block dynamically."""
         target_block = self.get_block(block_id)
         if not target_block:
              return 'NOT_FOUND'
         if target_block.get('transaction_type') == 'GENESIS':
              return 'ACTIVE' # Genesis is always active conceptually

         # Check subsequent blocks in the chain for actions related to this block_id
         # Iterate through the actual chain list, not just the index which might have stale status
         is_superseded = False
         is_deleted = False
         # Start checking from the block *after* the target_block_id in the chain
         # We need to find the index of target_block_id in self.chain list first
         target_index_in_chain = -1
         try:
              # Find the index of the target block in the chain list
              target_index_in_chain = next(i for i, block in enumerate(self.chain) if block.get('block_id') == block_id)
         except StopIteration:
              # Block not found in chain list - should not happen if found in index, but defensive
              logging.warning(f"Block ID {block_id} found in index but not in chain list during status check.")
              return 'NOT_FOUND' # Or based on index status? Let's rely on chain list as source of truth


         # Iterate from the element *after* the target block's index
         for block in self.chain[target_index_in_chain + 1:]:
              trans_type = block.get('transaction_type')
              metadata = block.get('metadata', {})

              if trans_type == 'UPDATE' and metadata.get('supersedes_block') == block_id:
                   is_superseded = True
                   # If superseded, its final state is determined unless the superseding block is deleted/superseded itself.
                   # For simplicity in this simulation, if a block is superseded, it stays superseded relative to the original.
                   # To be truly robust, we'd need to trace the *latest* block in the chain related to this patient/record lineage.
                   # For this logic, finding a superseding block means the original is superseded.
                   # break # Exit early if superseded found

              if trans_type == 'DELETE' and metadata.get('deleted_block_id') == block_id:
                   is_deleted = True
                   # If deleted, its final state is deleted. This takes precedence over superseded.
                   break # Exit early if deleted found

         # Priority: DELETED > SUPERSEDED > ACTIVE
         if is_deleted:
              return 'DELETED'
         elif is_superseded:
              return 'SUPERSEDED'
         else:
             # If no subsequent UPDATE or DELETE marker is found for this block_id, it is ACTIVE
             # We can optionally check its *own* status field as a cross-reference, but the dynamic check is the source of truth.
             return 'ACTIVE'


    def get_chain_view(self, patient_id=None, include_history=False):
        """
        Provides a view of the blockchain, optionally filtered by patient_id.
        Determines current status dynamically.

        Args:
            patient_id (str, optional): Filter by patient ID. Defaults to None (all patients).
            include_history (bool, optional): If True, includes SUPERSEDED/DELETED blocks.
                                              If False, only includes ACTIVE records. Defaults to False.

        Returns:
            list: A list of blocks matching the criteria.
        """
        view = []
        # Iterate through the actual chain list
        for block in self.chain:
            # Skip Genesis unless specifically needed (not for patient views)
            if block.get('transaction_type') == 'GENESIS':
                continue

            # Filter by patient ID if specified
            if patient_id is not None and block.get('patient_id') != patient_id:
                continue

            # Determine status dynamically based on the full chain
            block_id = block.get('block_id')
            if block_id is None:
                 logging.warning(f"Skipping block with missing block_id: {block.get('block_hash', 'N/A')[:16]}...")
                 continue  # Skip malformed blocks

            status = self.get_block_status(block_id) # Use dynamic status check

            # Create a copy to add dynamic status without altering original chain block
            block_view = block.copy()
            block_view['current_status'] = status  # Add dynamic status to the returned block view

            # Apply history filter
            if include_history:
                # Include all blocks (ACTIVE, SUPERSEDED, DELETED, MARKER, GENESIS if not skipped)
                view.append(block_view)
            elif status == 'ACTIVE':
                # Only include ACTIVE blocks if history is not requested
                view.append(block_view)
            # else: # If not include_history and not ACTIVE, the block is excluded

        # Sort view by block_id descending for displaying newest first
        view = sorted(view, key=lambda x: x.get('block_id', -1), reverse=True)

        return view


    def clear_all_data(self, super_admin_password):
         """
         Clears all blockchain and IPFS data. Requires super admin password.
         WARNING: This operation is irreversible.
         """
         # This method needs to be implemented or called from app.py.
         # Based on app.py, it's already called. We just need to ensure it functions.
         # The implementation would involve deleting the blockchain file and calling ipfs_manager.clear_storage
         logging.critical("Attempting to clear all blockchain data...") # Use critical level for this
         if super_admin_password != "admin.123": # Verify password again for safety
              logging.error("Clear all data failed: Incorrect super admin password.")
              raise PermissionError("Incorrect super admin password.")

         try:
              # Delete blockchain file
              if os.path.exists(BLOCKCHAIN_FILE):
                   os.remove(BLOCKCHAIN_FILE)
                   logging.info(f"Blockchain file {BLOCKCHAIN_FILE} deleted.")
              else:
                   logging.warning(f"Blockchain file {BLOCKCHAIN_FILE} not found during clear operation.")

              # Clear in-memory chain and index
              self.chain = []
              self.block_index = {}
              self.patient_name_cache = {}
              logging.info("In-memory blockchain state cleared.")

              # Audit log entry for clearing data (optional, as log might be cleared too)
              # If audit log is separate and intended to survive, this is fine.
              try:
                   self._log_audit('CLEAR_ALL_DATA', {'user': 'SUPER_ADMIN (via clear function)'})
                   # If audit log should survive clear, this would need to be handled externally
              except Exception as e:
                   logging.warning(f"Failed to write audit log for CLEAR_ALL_DATA: {e}")


              # Note: IPFS storage clearing is handled by calling ipfs_manager.clear_storage from app.py
              logging.critical("Blockchain data cleared. Ensure IPFS storage is also cleared via IPFSManager.clear_storage.")


         except Exception as e:
              logging.error(f"Failed to clear blockchain data: {e}", exc_info=True)
              raise RuntimeError("An error occurred while clearing blockchain data.") from e