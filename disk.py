from sector import Sector
import win32file
import subprocess
# import shutil
import re

class Disk:
    def __init__(self, serial: str, skip: int = 0):
        self.skip = skip
        self.emptyspace = 0
        self.serial = serial
        # self.serial_mount = self.get_serial_mount()
        self.drive_info = self.get_drive_info()
        try:
            self.physical_drive = self.drive_info["device_id"]
        except Exception as e:
            print(f"No device found, please enter a valid serial in FS.py ({e})")
            return
        # sizes
        self.disk_size = int(self.drive_info["size"])
        self.number_of_sectors = int(self.drive_info["sectors"])
        self.sector_size = self.disk_size//self.number_of_sectors
        #skip
        self.number_of_sectors -= self.skip
        self.disk_size -= self.skip * self.sector_size
        
        self.read_disk_handle = None
        print(f"Serial: {self.serial}")#, Letter: {self.letter}, mount: {self.serial_mount}")
        print(f"Disk size: {self.to_humain_readable(self.disk_size)}")
        print(f"Sector size: {self.sector_size} octets")
        print(f"No of sectors: {int(self.disk_size / self.sector_size)}")
        print(f"Physical drive: {self.physical_drive}")

    def to_humain_readable(self,size: int):
        """Convert bytes to humain readable format"""
        for unit in ['o', 'Ko', 'Mo', 'Go', 'To']:
            if size < 1024.0:
                break
            size /= 1024.0
        return f"{size:.2f} {unit}"

    def list_disks(self):
        cmdoutput = subprocess.check_output("wmic diskdrive get SerialNumber, DeviceID, Size, TotalSectors", shell=True)
        cmdoutput = cmdoutput.decode(errors="ignore")
        cmdoutput = cmdoutput.split("\r\n")[1:]#remove header
        result = {}
        for line in cmdoutput:
            while "  " in line:
                line = line.replace("  ", " ")
            line = line.split(" ")
            if len(line) > 1:
                result[line[1]] = {
                    "device_id": line[0],
                    "size": line[2],
                    "sectors": line[3]
                }
        return result

    def get_drive_info(self):
        """drive info using wmic:"""
        result = self.list_disks()
        if self.serial in result:
            return result[self.serial]
        return None

    def get_serial_mount(self):
        """mountvol then parse the output:"""
        result = subprocess.check_output("mountvol", shell=True)
        result = result.decode(errors="ignore").replace("\r\n", "")
        reg = re.compile(r"\\\\\?\\")
        result = reg.split(result)[1:]
        reg = re.compile(r"(Volume{[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}})|([A-Z]:)\\")
        result = [reg.findall(i) for i in result]
        result = {
            i[1][1]:f"\\\\?\\{i[0][0]}\\" for i in result if len(i) == 2
        }
        return result[self.letter]

    def read(self):
        """Read all sectors from the disk"""
        for sector_number in range(0, self.disk_size // self.sector_size - 1):
            try:
                sector_data = self.read_sector(sector_number)
            except Exception as e:
                print(f"Error reading sector {sector_number}: {e}")
                continue
            sector = Sector(sector_number, sector_data)
            yield sector
        win32file.CloseHandle(self.read_disk_handle)
        self.read_disk_handle = None

    def read_sector(self, sector_number: int)->bytes:
        """Read a specific sector by its number"""
        try:
            offset = sector_number * self.sector_size + self.skip * self.sector_size
            if self.read_disk_handle is None:
                self.read_disk_handle = self.get_handle()
            win32file.SetFilePointer(self.read_disk_handle, offset, win32file.FILE_BEGIN)
            result, data = win32file.ReadFile(self.read_disk_handle, self.sector_size)
            return data
        except Exception as e:
            print(f"Error reading sector {sector_number}: {e}")
            return None

    def write_sector(self, sector_number, data):
        """Write data to a specific sector"""
        if len(data) != self.sector_size:
            raise ValueError(f"Data size must be exactly {self.sector_size} bytes")
        write_disk_handle = self.get_handle()
        try:
            # Set the file pointer to the correct sector
            position = sector_number * self.sector_size + self.skip * self.sector_size
            win32file.SetFilePointer(write_disk_handle, position, win32file.FILE_BEGIN)
                # Write the data to the sector
            win32file.WriteFile(write_disk_handle, data)
        except Exception as e:
            print(f"Error writing to sector {sector_number}: {e}")
        win32file.CloseHandle(write_disk_handle)
        write_disk_handle = None

    def get_handle(self):
        """Get the handle to the disk"""
        return win32file.CreateFile(
            self.physical_drive,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE,
            None,
            win32file.OPEN_EXISTING,
            0,
            None
        )

    # def umount(self):
    #     """Unmount the disk"""
    #     subprocess.run(f"mountvol {self.letter} /p", shell=True)
    #     print("Volume unmounted successfully")

    # def mount(self):
    #     """Mount the disk"""
    #     subprocess.run(f"mountvol {self.letter} {self.serial_mount}", shell=True)
    #     print("Volume mounted successfully")

    def find_empty_sectors(self, after:int):
        """Find empty sectors on the disk"""
        print("Finding empty sectors")
        for sector_n in range(self.skip + after, int(self.disk_size / self.sector_size - 1)):
            sector = self.read_sector(sector_n)
            if not any(sector):
                self.emptyspace = sector_n
                break
        print(f"Empty sector found: {self.emptyspace}")
        win32file.CloseHandle(self.read_disk_handle)
        self.read_disk_handle = None
        return self.emptyspace

    def find_string(self, string: str):
        """Find a string in the disk"""
        for sector in self.read():
            if sector.data and string in sector.data.decode(errors="ignore", encoding="utf-8"):
                print(f"String found in sector {sector.number}: {sector.data}")
                win32file.CloseHandle(self.read_disk_handle)
                self.read_disk_handle = None
                return sector.number

    def empty_sector_with_data(self, data: bytes):
        """create a sector and prepad it with the data"""
        if len(data) > self.sector_size:
            raise ValueError(f"Data size must be less than {self.sector_size} bytes")
        sector = data + b"\x00" * (self.sector_size - len(data))
        return sector
    
    def reset_disk(self):
        """reset the FULL disk"""
        print("Resetting disk")
        size = (1024**2)*5
        offset = 0
        for sector_n in range(0, size // self.sector_size):
            sector_n += offset
            sector = self.read_sector(sector_n)#read doesn't implement skip
            if any(sector):
                self.write_sector(sector_n-offset, self.empty_sector_with_data(b""))
        self.emptyspace = 0
        

if __name__ == "__main__":
    serial = ""
    skip = 0
    disk = Disk(serial, skip)
    # disk.umount()
    input("Press enter to continue")
# ----------- TEST ------------
    # sector_n = disk.find_string("FLAG")
    # print(f"found empty sector {sector_n}")
    # sector = disk.empty_sector_with_data(b"FLBG")
    # disk.write_sector(sector_n, sector)
    # sector = disk.read_sector(sector_n)
    # assert sector == disk.empty_sector_with_data(b"FLBG")
    # disk.mount()
    size = (1024**2)*5
    print(disk.sector_size, size, disk.sector_size)
    for i in range(disk.sector_size, size, disk.sector_size):
        sector = disk.read_sector(i)
        if any(sector):
            print(f"sector {i//disk.sector_size}: {sector}")
            disk.write_sector(i//disk.sector_size, disk.empty_sector_with_data(b""))
