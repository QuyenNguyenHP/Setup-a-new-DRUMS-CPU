
import os
import subprocess
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class AscFileHandler(FileSystemEventHandler):
    def __init__(self, directory, remote_paths, ports, check_interval=60):
        self.directory = directory
        self.remote_paths = remote_paths
        self.ports = ports
        self.check_interval = check_interval
        self.transfer_pending_files()
        
    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.asc'):
            self.transfer_file(event.src_path)

    def transfer_file(self, file_path):
        print(f"Detected new file for transfer: {file_path}")
        success = True  # Flag to check if all transfers were successful
        for remote_path, port in zip(self.remote_paths, self.ports):
            print(f"Attempting to transfer {file_path} to {remote_path} using port {port if port else 'default'}")
            if port:
                result = subprocess.run(["scp", "-P", str(port), file_path, remote_path], capture_output=True)
            else:
                result = subprocess.run(["scp", file_path, remote_path], capture_output=True)
            if result.returncode == 0:
                print(f"Transfer to {remote_path} successful: {file_path}")
            else:
                success = False  # Mark as failed if any transfer fails
                print(f"Transfer to {remote_path} failed: {file_path}\n{result.stderr.decode()}")

        if success:
            os.remove(file_path)
            print(f"File {file_path} deleted after successful transfer.")
        else:
            print(f"File {file_path} not deleted due to failed transfer.")

    def transfer_pending_files(self):
        while True:
            files = [f for f in os.listdir(self.directory) if f.endswith('.asc')]
            if files:
                print(f"Found {len(files)} pending .asc files for transfer.")
            for file_name in sorted(files):
                file_path = os.path.join(self.directory, file_name)
                print(f"Transferring pending file: {file_path}")
                self.transfer_file(file_path)
            time.sleep(self.check_interval)

if __name__ == "__main__":
    directory_to_monitor = "/home/drums/asc/"
    remote_server_paths = [
        #"devdb@dsing.softether.net:/home/devdb/incoming/",
        "opc@129.150.37.135:/input/EDA_NK"
    ]
    ports = [None]  # Specify ports corresponding to each remote path, None for default port
    check_interval = 60  # Check for unsent files every 60 seconds

    event_handler = AscFileHandler(directory_to_monitor, remote_server_paths, ports, check_interval)
    observer = Observer()
    observer.schedule(event_handler, directory_to_monitor, recursive=False)
    observer.start()

    try:
        while True:
            pass  # Keep the script running
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

