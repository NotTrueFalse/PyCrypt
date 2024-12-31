from disk import Disk
from custom_crypt import SectorCrypt
import os
from tkinter import *
from tkinter.filedialog import askopenfilename
from typing import Generator
import time

class Inode:
    """Inode class to handle inode operations"""
    def __init__(self, data:bytes, offset:int=0):
        self.valid = data[0] == 1
        if not self.valid:
            self.size = 0
            self.name = ""
            self.direct = [0]*4
            self.indirect = 0
            self.double_indirect = 0
            self.position = offset
            return
        self.size = int.from_bytes(data[1:8], byteorder="big")
        too_big = 1024**4
        if self.size > too_big or self.size <= 0:
            raise ValueError(f"File size too big: {self.size} bytes")
        self.name = data[8:40].decode('utf-8').strip("\x00")
        self.direct = [int.from_bytes(data[i:i+4], byteorder="big") for i in range(40, 56, 4)]
        self.indirect = int.from_bytes(data[56:60], byteorder="big")
        self.double_indirect = int.from_bytes(data[60:64], byteorder="big")
        self.position = offset

    def __str__(self):
        return f"Inode: {self.name} ({self.size} bytes)"

    def to_bytes(self):
        data = b"\x01" if self.valid else b"\x00"
        data += self.size.to_bytes(7, byteorder="big")
        data += self.name.encode('utf-8').ljust(32, b"\x00")
        data += b"".join([i.to_bytes(4, byteorder="big") for i in self.direct])
        data += self.indirect.to_bytes(4, byteorder="big")
        data += self.double_indirect.to_bytes(4, byteorder="big")
        return data

DEBUG = 0

class FileSystem:
    """Filesystem class to handle file operations
    block_size: 4ko (8*512 (8*sector_size))
    inode: 64 octets (each pointer is 4 octets)
        - valid (1 octet)
        - size (7 octets)
        - name # 32 octets
        - Direct[0] (points to Data block)
        - Direct[1]
        - Direct[2]
        - Direct[3]
        - Indirect (points to a Pointer block)
        - Double Indirect (points to a Pointer block)
        (hidden param)
        - position (offset in inode block)

    Data block: block_size octets

    Pointer block: block_size/4 octets (each pointer is 4 octets)
    
    block_size/64 = number of inodes per block
    
    block_bitmap: 1 bit per block (1: used, 0: free)

    Superblock: (each part is 4 octets)
        - magic number
        - number of block_bitmap blocks
        - number of inode blocks
        - number of inodes in inode blocks

    sector structure:
        - 1st sector: superblock
        - 2nd to free_block/32768: block_bitmap blocks
        - free_block/32768 to number_of_inode_blocks: inode blocks
        - rest of the blocks: data blocks

    """
    magic_number = b"\x53\x46\x53\x45"  # SFSE # Super FileSystem Explorer

    def __init__(self,skip:int,passwd=None,pin= None):
        """Explorer class to handle disk and crypt"""
        with open("config.ini", "r") as f:
            serial = f.readline().strip().split("=")[1]
        self.disk = Disk(serial, skip)
        passwd = input("Enter password: ") if passwd is None else passwd
        pin = input("Enter PIN: ") if pin is None else pin
        self.crypt_module = SectorCrypt(passwd, pin)
        self.mode = "crypt"
        self.number_of_inode_blocks = 0
        self.block_size = 4096# NEED TO BE CONGRUENT TO SECTOR SIZE !!!
        self.init_fs()
        # self.bitmap = self.read_bitmap()#very slow way of loading everything
        self.bitmap = {}
        self.hot_bitmap_blocks = {}#edit bitmap blocks in memory to avoid writing to disk multiple times
        self.directory = self.read_inodes()

        
    def read_sector(self, sector:int):
        if DEBUG:print(f"Reading sector {sector}")
        sector_data = self.disk.read_sector(sector,self.block_size)
        if self.mode == "crypt":
            if sector_data is None or not any(sector_data):
                return b""
            decrypted_sector = self.crypt_module.decrypt_sector(sector, sector_data)
            return decrypted_sector
        else:
            return sector_data

    def write_sector(self, sector:int, data:bytes):
        """Write data to sector
        - If data is less than sector size, it will be padded with null bytes
        - /!\ Warning: Data must be less than sector size
        - /!\ Sector will be overwritten
        """
        if DEBUG:print(f"Writing to sector {sector}")
        if self.mode == "crypt":
            encrypted_sector = self.crypt_module.encrypt_sector(sector, data.ljust(self.block_size, b"\x00"))
            self.disk.write_sector(sector, encrypted_sector)
        else:
            self.disk.write_sector(sector, data.ljust(self.block_size, b"\x00"))
        return 1

    def init_fs(self,force=False):
        """Initialize filesystem:
            - magic number
            - number of bitmap blocks
            - number of inode blocks
            - number of inodes in inode blocks
        """
        superblock = self.read_sector(0)
        self.number_of_blocks = self.disk.number_of_sectors//(self.block_size//self.disk.sector_size)
        self.number_of_inode_blocks = round((self.number_of_blocks-1)/100_000)#.001% of disk size (1 inode block per 1000 sectors)
        #self.disk.block_size*8 => number of bits in a block
        self.number_of_bitmap_blocks = (self.number_of_blocks-self.number_of_inode_blocks-1)//(self.block_size*8)#num of blocks - superblock - inode blocks (free space)
        self.offset_data = self.number_of_bitmap_blocks + self.number_of_inode_blocks + 1
        if superblock[:4] == self.magic_number and not force:return
        print("[*] Initializing filesystem...")
        superblock = self.magic_number
        superblock += self.number_of_bitmap_blocks.to_bytes(4, byteorder="big")
        superblock += self.number_of_inode_blocks.to_bytes(4, byteorder="big")
        superblock += b"\x00\x00\x00\x00"#none for now
        self.write_sector(0, superblock)
        # Create bitmap + inode blocks
        if not force:#already done
            for blockpos in range(1, self.offset_data):
                self.write_sector(blockpos, b"\x00"*self.block_size)
                #print(f"[*] {blockpos}/{self.offset_data} ({round(blockpos/self.offset_data*100)}%)", end="\r")
        return
    
    def update_superblock(self):
        """Update superblock:
            - number of inodes in inode Block
        """
        superblock = self.read_sector(0)
        superblock = superblock[:12]#skip magic number + number of bitmap blocks + number of inode blocks
        superblock += len(self.directory).to_bytes(4, byteorder="big")
        self.write_sector(0, superblock)
        return
    
    def load_bitmap(self,block_number:int):
        """Load bitmap for a specific block"""
        bitmap_block = self.read_sector(block_number)
        self.hot_bitmap_blocks[block_number] = bitmap_block
        for byte_number in range(self.block_size):
            for bit_number in range(8):
                if bitmap_block[byte_number] & (1<<bit_number):
                    self.bitmap[self.offset_data+(block_number-1)*self.block_size+byte_number*8+bit_number] = 1
        return
    
    def xor_bitmap(self, block_pos:int):
        """Add/Remove block_pos from bitmap:
        - Read bitmap block
        - invert bit at block_pos position
        """
        block_pos -= self.offset_data
        bitmap_block_number = block_pos//self.block_size+1#skip superblock
        if bitmap_block_number not in self.hot_bitmap_blocks:
            self.load_bitmap(bitmap_block_number)
        bitmap_block = self.hot_bitmap_blocks[bitmap_block_number]
        byte_number = (block_pos%self.block_size)//8
        bit_number = (block_pos%self.block_size)%8
        bitmap_block = bitmap_block[:byte_number] + bytes([bitmap_block[byte_number]^(1<<bit_number)]) + bitmap_block[byte_number+1:]
        self.hot_bitmap_blocks[bitmap_block_number] = bitmap_block
        # self.write_sector(bitmap_block_number, bitmap_block)
        if DEBUG:print(f"[*] {block_pos} {bitmap_block_number} {byte_number} {bit_number}")

    def save_bitmap(self):
        """Save bitmap to disk"""
        for block_pos in self.hot_bitmap_blocks:
            self.write_sector(block_pos, self.hot_bitmap_blocks[block_pos])
            # print(f"[*] Saving bitmap block", end="\r")
        self.hot_bitmap_blocks = {}#clear hot blocks
        return

    def read_inodes(self):
        """Read all inodes:
        - Read all inode blocks
        - Return list of valid inodes
        """
        print("[*] Loading inodes...")
        directory = {}
        for block_position in range(self.number_of_bitmap_blocks+1, self.offset_data+1):
            inode_block = self.read_sector(block_position)
            offset_position = block_position-(self.number_of_bitmap_blocks+1)
            max_inode_in_block = self.block_size//64
            for j in range(0, self.block_size, 64):#inode size 64
                try:
                    #j//max_inode_in_block => position in inode block
                    #offset_position*self.block_size => offset in inode blocks (in wich block we are)
                    inode = Inode(inode_block[j:j+64], j//max_inode_in_block+(offset_position*self.block_size)//max_inode_in_block)
                except Exception as e:
                    if DEBUG:print(f"[-] Error reading inode: {e}")
                    continue
                # if j == 0 and block_position == self.number_of_bitmap_blocks+1:print(inode_block[j:j+64])
                if inode.valid:directory[inode.name] = inode
            # percentage = block_position-(self.number_of_bitmap_blocks+1)
            # print(f"[*] {percentage}/{self.offset_data-self.number_of_bitmap_blocks+1} ({round(percentage/(self.offset_data-self.number_of_bitmap_blocks+1)*100)}%)", end="\r")
        return directory
    
    def add_inode(self, inode:Inode):
        """Update needed inode blocks:
        - for all inode blocks, if block is full skip, else write inodes
        """
        for block_position in range(self.number_of_bitmap_blocks+1, self.offset_data+1):
            inode_block = self.read_sector(block_position)
            offset_position = block_position-(self.number_of_bitmap_blocks+1)
            max_inode_in_block = self.block_size//64
            for j in range(0, self.block_size, 64):
                test_inode = Inode(inode_block[j:j+64], j//max_inode_in_block+(offset_position*self.block_size)//max_inode_in_block)
                if not test_inode.valid:
                    inode_block = inode_block[:j] + inode.to_bytes() + inode_block[j+64:]
                    self.write_sector(block_position, inode_block)
                    return
        raise Exception("Maximum number of inodes reached")

    def update_node(self, inode:Inode):
        """Update inode:
        - Write inode to inode block
        position: position in inode block (0-n) (64 octets per inode and we have block_size/64 inodes per block)
        """
        offset = self.number_of_bitmap_blocks+1
        max_inode_in_block = self.block_size//64
        inode_block = self.read_sector(offset+(inode.position//max_inode_in_block))
        inode_block = inode_block[:64*(inode.position%max_inode_in_block)] + inode.to_bytes() + inode_block[64*(inode.position%max_inode_in_block)+64:]
        self.write_sector(offset+(inode.position//max_inode_in_block), inode_block)
        return True

    def find_file(self, filename:str)->Inode:
        """Find file in directory:
        - Search for file in self.directory
        - Read inode
        """
        if filename in self.directory:
            return self.directory[filename]
        return None

    def read_file(self, filename:str)->Generator[bytes, None, None]:
        """Read file from disk:
        - Search for file in directory (in memory)
        - Read inode
        - Read data blocks
        """
        inode = self.find_file(filename)
        try:
            if inode is None:
                return None
            for i in range(4):
                if inode.direct[i] == 0:
                    break
                yield self.read_sector(inode.direct[i])
            if inode.indirect != 0:
                indirect_block = self.read_sector(inode.indirect)
                for i in range(0, self.block_size, 4):
                    pointer = int.from_bytes(indirect_block[i:i+4], byteorder="big")
                    if pointer == 0:
                        break
                    if DEBUG:print(f"[*] Reading indirect block {pointer}")
                    yield self.read_sector(pointer)
            if inode.double_indirect != 0:
                double_indirect_block = self.read_sector(inode.double_indirect)
                for i in range(0, self.block_size, 4):
                    indirect_pointer = int.from_bytes(double_indirect_block[i:i+4], byteorder="big")
                    if pointer == 0:
                        break
                    if DEBUG:print(f"[*] Reading double indirect block {indirect_pointer}")
                    indirect_block = self.read_sector(indirect_pointer)
                    for j in range(0, self.block_size, 4):
                        pointer = int.from_bytes(indirect_block[j:j+4], byteorder="big")
                        if pointer == 0:
                            break
                        if DEBUG:print(f"[*] Reading indirect block {pointer}")
                        yield self.read_sector(pointer)
        except KeyboardInterrupt:
            print("[-] Cancelled reading file")
            return None
        return

    def find_free_inode(self)->Inode:
        """Find free inode:
        - Read all inodes
        - Return first free inode
        """
        for i in range(self.number_of_bitmap_blocks+1, self.offset_data):
            inode_block = self.read_sector(i)
            for j in range(0, self.block_size, 64):#inode size 64
                inode = Inode(inode_block[j:j+64], j)
                if not inode.valid:
                    return inode
        return None

    def create_file(self, filename:str,path:str):
        """Create file on disk:
            - Search for file in directory (in memory)
            - If file exists, return False
            - Find free inode
            - Write data to data blocks
            - Update inode
            - Update directory
        """
        if filename in self.directory:
            return False
        inode = self.find_free_inode()
        if inode is None:
            return False
        inode.size = os.path.getsize(path)
        inode.name = filename
        inode.valid = True
        inode.direct = [0]*4
        inode.indirect = 0
        inode.double_indirect = 0
        test = self.write_data(inode, path)
        if test == -1:
            return False
        self.add_inode(inode)
        self.directory[filename] = inode
        self.update_superblock()
        self.save_bitmap()
        return True
    
    def find_free_data_block(self)->int:
        """Find free data block:
        - will use bitmap to find free data block
        - reverse inode position from data block position, if its deleted, return it
        """
        #USE self.bitmap
        for position in range(self.offset_data, self.number_of_blocks):#skip superblock, bitmap blocks, inode blocks and go to max data blocks (not sector)
            #we divide by quotien to get the real block position
            if position not in self.bitmap or self.bitmap[position] == 0:
                self.xor_bitmap(position)
                self.bitmap[position] = 1
                return position
        return None

    def loading(self,action:str,size:int,ogsize:int,t1:float):
        """Loading bar"""
        percentage = round((ogsize-size)/ogsize*100)
        print(f"[*] {action} file, {self.disk.to_humain_readable(size)} remaining ({percentage}%)", end="\r")

    def write_data(self, inode:Inode, path:str):
        """Write data to disk:
        - for 4 first data blocks, write data
        - if data > 4*self.block_size, write to indirect block
        - for indirect block, write pointers to data blocks
        - if data > 4*self.block_size+1024*self.block_size, write to double indirect block
        - for double indirect block, write pointers to indirect blocks
        """
        # ogsize = len(data)
        # t1 = time.time()
        if os.path.getsize(path) > self.block_size*(4+1024+1024*1024):
            print("[-] File too big")
            return -1
        file = open(path, "rb")
        for i in range(4):
            data = file.read(self.block_size)
            if not data:
                break
            if inode.direct[i] == 0:
                inode.direct[i] = self.find_free_data_block()
            self.write_sector(inode.direct[i], data)
            # self.loading("Writing",len(data),ogsize,t1)
        if data:
            if inode.indirect == 0:
                inode.indirect = self.find_free_data_block()
            indirect_block = b""
            for i in range(0, self.block_size, 4):
                data = file.read(self.block_size)
                if not data:
                    break
                pointer = self.find_free_data_block()
                indirect_block += pointer.to_bytes(4, byteorder="big")
                self.write_sector(pointer, data)
                # self.loading("Writing",len(data),ogsize,t1)
            self.write_sector(inode.indirect, indirect_block)
            if data:
                try:
                    if inode.double_indirect == 0:
                        inode.double_indirect = self.find_free_data_block()
                    double_indirect_block = b""
                    for i in range(0, self.block_size, 4):
                        if not data:
                            break
                        indirect_pointer = self.find_free_data_block()
                        double_indirect_block += indirect_pointer.to_bytes(4, byteorder="big")
                        indirect_block = b""
                        for j in range(0, self.block_size, 4):
                            data = file.read(self.block_size)
                            if not data:
                                break
                            pointer = self.find_free_data_block()
                            indirect_block += pointer.to_bytes(4, byteorder="big")
                            self.write_sector(pointer, data)
                            # self.loading("Writing",len(data),ogsize,t1)
                        self.write_sector(indirect_pointer, indirect_block)
                    self.write_sector(inode.double_indirect, double_indirect_block)
                except KeyboardInterrupt:
                    print("[-] Cancelled writing file")
                    return -1
        return 1
    
    def delete_file(self, filename:str):
        """Delete file from disk:
        - Search for file in directory (in memory)
        - Read inode
        - Update bitmap
        - Update directory
        - Update inode
        """
        inode = self.find_file(filename)
        if inode is None:
            return False
        for i in range(4):
            if inode.direct[i] == 0:
                break
            self.xor_bitmap(inode.direct[i])
            self.bitmap[inode.direct[i]] = 0
        if inode.indirect != 0:
            indirect_block = self.read_sector(inode.indirect)
            for i in range(0, self.block_size, 4):
                pointer = int.from_bytes(indirect_block[i:i+4], byteorder="big")
                if pointer == 0:
                    break
                self.xor_bitmap(pointer)
                self.bitmap[pointer] = 0
            self.xor_bitmap(inode.indirect)
            self.bitmap[inode.indirect] = 0
        if inode.double_indirect != 0:
            double_indirect_block = self.read_sector(inode.double_indirect)
            for i in range(0, self.block_size, 4):
                indirect_pointer = int.from_bytes(double_indirect_block[i:i+4], byteorder="big")
                if pointer == 0:
                    break
                indirect_block = self.read_sector(indirect_pointer)
                for j in range(0, self.block_size, 4):
                    pointer = int.from_bytes(indirect_block[j:j+4], byteorder="big")
                    if pointer == 0:
                        break
                    self.xor_bitmap(pointer)
                    self.bitmap[pointer] = 0
                self.xor_bitmap(indirect_pointer)
                self.bitmap[indirect_pointer] = 0
            self.xor_bitmap(inode.double_indirect)
            self.bitmap[inode.double_indirect] = 0
        inode.valid = False
        self.update_node(inode)
        del self.directory[filename]
        self.update_superblock()
        self.save_bitmap()
        return True
    
    def rename_file(self, oldname:str, newname:str):
        """Rename file:
        - Search for file in directory (in memory)
        - Update directory
        - Update inode
        """
        inode = self.find_file(oldname)
        if inode is None:
            print("File not found")
            return False
        inode.name = newname
        self.update_node(inode)
        self.directory[newname] = inode
        del self.directory[oldname]
        return True
    
    def reset_disk(self):
        """Fast reset so just write 0s to superblock+bitmap+inode blocks"""
        try:
            stop = self.offset_data
            for i in range(stop):
                self.write_sector(i, b"\x00"*self.block_size)
                #print(f"[*] Resetting disk, {i}/{stop} ({round(i/(stop)*100)}%)", end="\r")
        except KeyboardInterrupt:
            print("[+] Skipped some blocks")
        self.directory = {}
        self.update_superblock()
        self.bitmap = {}
        self.hot_bitmap_blocks = {}
        self.init_fs(force=True)
        return
    
    def calculate_used_space(self):
        """Calculate used space on disk"""
        used_space = 0
        for inode_name in self.directory:
            inode = self.directory[inode_name]
            used_space += inode.size
        return used_space
    
    def read_test(self):
        """Read test"""
        print("SuperBlock:", self.read_sector(0))
        print("1st bitmap block:", self.read_sector(1))
        print("1st inode block:", self.read_sector(self.number_of_bitmap_blocks+1), self.number_of_bitmap_blocks+1)
        print("1st data block:", self.read_sector(self.offset_data))
        return

if __name__ == "__main__":
    def main():
        skip = 0
        instance = FileSystem(skip)
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            print("\nWelcome to Super FileSystem Explorer")
            print(f"Disk: {instance.disk.serial}, {instance.disk.to_humain_readable(instance.disk.disk_size)}")
            max_file_size = instance.block_size*(4+1024+1024*1024)#4 direct + 1024 pointer (indirect) + 1024*1024 pointer (double indirect)
            print(f"Max file size: {instance.disk.to_humain_readable(max_file_size)}")
            total_inodes = instance.number_of_inode_blocks*64
            print(f"inodes: {len(instance.directory)}/{total_inodes} ({round(len(instance.directory)/total_inodes*100)}%)")
            print(f"Used space: {instance.disk.to_humain_readable(instance.calculate_used_space())}")
            if DEBUG:print(f"blocks: BitMap: {instance.number_of_bitmap_blocks}, Inode: {instance.number_of_inode_blocks}")
            print("\nOptions: [list, read <file>, dump <file>, create <file>, delete <file>, rename <old> <new>, reset, exit, benchmark]")
            command = input("> ")
            if command == "list":
                print("Files:")
                for filename in instance.directory:
                    print(f"  {filename} ({instance.disk.to_humain_readable(instance.directory[filename].size)}) \
                        {instance.directory[filename].direct} {instance.directory[filename].indirect} {instance.directory[filename].double_indirect}")
            elif command.startswith("read "):
                filename = command.split(" ")[1]
                for data in instance.read_file(filename):
                    try:
                        print(data.decode('utf-8'), end="")
                    except UnicodeDecodeError:
                        print("Cannot decode data")
            elif command.startswith("dump "):
                filename = command.split(" ")[1]
                fsize = instance.find_file(filename).size
                path = askopenfilename()
                with open(path, "wb") as f:
                    written = 0
                    for chunk in instance.read_file(filename):#prevent memory overflow
                        f.write(chunk)
                        written += len(chunk)
                        print(f"Dumping file, {instance.disk.to_humain_readable(written)}/{instance.disk.to_humain_readable(fsize)} ({round(written/fsize*100)}%)", end="\r")
                    f.close()
                print("File dumped successfully")
            elif command.startswith("create "):
                filename = command.split(" ")[1]
                path = askopenfilename()
                if instance.create_file(filename,path) != -1:
                    print("File created successfully")
                else:
                    print("Failed to create file")
            elif command.startswith("delete ") or command.startswith("del "):
                filename = command.split(" ")[1]
                if instance.delete_file(filename):
                    print("File deleted successfully")
                else:
                    print("File not found")
            elif command.startswith("rename "):
                filename = command.split(" ")[1]
                newname = command.split(" ")[2]
                if instance.rename_file(filename, newname):
                    print("File renamed successfully")
                else:
                    print("File not found")
            elif command == "reset":
                instance.reset_disk()
                print("Disk reset")
            elif command == "exit":
                break
            elif command == "benchmark":
                #speed for 5Mo file read/write + test with and without crypt
                if not input("This will break the filesystem, are you sure? (y/n) ").startswith("y"):continue
                print("Benchmarking...")
                data = os.urandom((1024**2)*5)
                with open("benchmark", "wb") as f:
                    f.write(data)
                    f.close()
                del data
                times  = {
                    "crypt":{},
                    "plain":{}
                }
                times["crypt"]["reset"] = time.time()
                instance.reset_disk()
                times["crypt"]["reset"] = time.time()-times["crypt"]["reset"]
                times["crypt"]["write"] = time.time()
                instance.create_file("benchmark", "benchmark")
                times["crypt"]["write"] = time.time()-times["crypt"]["write"]
                times["crypt"]["read"] = time.time()
                for data in instance.read_file("benchmark"):
                    pass
                times["crypt"]["read"] = time.time()-times["crypt"]["read"]
                times["crypt"]["delete"] = time.time()
                instance.delete_file("benchmark")
                times["crypt"]["delete"] = time.time()-times["crypt"]["delete"]
                instance.mode = "plain"
                times["plain"]["reset"] = time.time()
                instance.reset_disk()
                times["plain"]["reset"] = time.time()-times["plain"]["reset"]
                times["plain"]["write"] = time.time()
                instance.create_file("benchmark", "benchmark")
                times["plain"]["write"] = time.time()-times["plain"]["write"]
                times["plain"]["read"] = time.time()
                for data in instance.read_file("benchmark"):
                    pass
                times["plain"]["read"] = time.time()-times["plain"]["read"]
                times["plain"]["delete"] = time.time()
                instance.delete_file("benchmark")
                times["plain"]["delete"] = time.time()-times["plain"]["delete"]
                print("\nResults:")
                for mode in times:
                    print(f"  {mode}:")
                    for action in times[mode]:
                        print(f"    - {action}: {round(times[mode][action],4)}s")
                instance.mode = "crypt"
                instance.reset_disk()
            elif command == "test":
                instance.read_test()
            else:
                print("Invalid command")
            input("Press Enter to continue...")
    main()