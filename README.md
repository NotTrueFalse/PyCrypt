# PyCrypt
Little project to mimic Veracrypt using python.

## Initialisation
The disk you want to use need to be formatted as RAW, you can use any disk utility.
Before running FS.py, modify it to add your disk serial number, that you can find using the commad : `wmic diskdrive`<br>
the script always as to be run as root because we're touching at disk sectors directly.

## The main idea
- create a virtual drive in memory mounted to a random letter
- when a user interacted with the volume (by creating a file / reading one, deleting one etc..), it would proxy the IRPs (I/O Request Packet) to python so I can manage them truly like veracrypt.

## My intention
- create a more robust and unpredictible version of veracrypt, by using argon2 for the password (with strong parameters) and using some shuffle and noise function on top of the AES_ECB.
- AES_ECB is bad because its predictable (there's no IV, so 2 sector could be identified as same), but with the layer of shuffle and noise this problem disappear (the seed is generated from the password hash and the sector number).

# FileSystem
- A really easy implementation of ext file system (based on [this](https://www3.nd.edu/~pbui/teaching/cse.30341.fa17/project06.html) )
- 1 block = 4096 bytes
- No directory system for now

## layout
- block 0 (superblock): magic number, number of bitmap blocks, number of inode blocks, number of inode in inode blocks
- block 1 to blocksize\*8: bitmap blocks, used to determine if a block is used or not
- block blocksize\*8 to blocksize\*8+.001% of disksize: inode blocks, used to store inode (or file if you prefer)
- the rest: block of data (used to store data or pointer to data or double pointer to data)
![system layout](https://github.com/NotTrueFalse/PyCrypt/blob/main/FS_layout.png?raw=true)

## system
the system is pretty simple, when we create a file it creates a new Inode, a 64 bytes variable used to store multiple things:
- isValid (byte 0)
- size (bytes 1 to 8)
- name (8 to 40)
- direct pointers to data block (40 to 44)
- direct (44 to 48)
- direct (...)
- direct (...)
- Indirect (points to a Pointer block) (56 to 60)
- Double Indirect (points to a Pointer block) (60 to 64)

When you write the data of the file on the disk, it saves using the bitmap the used blocks, to trace wich block is free or unused (0 = free, 1 used),
the max size for a file is 4GB (block_size\*(4+1024+1024\*1024): 4 direct + 1024 pointer (indirect) + 1024\*1024 pointer (double indirect))

# Options
- read / create / dump / delete files
- reset the disk
- benchmark

# Password/Pin and hasing stuff
- pin: shake_256(pin).digest(16)
- password: argon2id(time_cost=2,memory_cost=1048576,parallelism=2,hash_len=32,salt_len=len(pin)).hash(password,salt=pin)
- final_key: sha256(password) (32 bytes)

# Encrypt Method
- generate a seed -> int(sha256(final_key+sector_number.tobyte(4,"big")),16)
- encrypted -> AES(final_key,MODE_ECB)
- shuffle_bytes(seed,encrypted_data)
- add_noise(seed,shuffled_data)

# Decrypt
basicly the inverse of encrypt (un-noise -> unshuffle -> decrypt)

# Benchmark 
using random 5MB of data for a external SSD (max 550 Mo/s)
- Encrypted:
    - reset: 0.2513s
    - write: 11.6727s
    - read: 9.675s
    - delete: 0.075s
- plain:
    - reset: 0.193s
    - write: 0.085s
    - read: 0.002s
    - delete: 0.081s

# PS
I know its slow and not finished, I'm publishing this project in the hope of some people explaining why and how to make this project better.
There are not drivers to mimic 1:1 veracrypt because you need to code in C/C++ to make one, and I'm not an expert in this langage, I tried to find one but none matched my intention.
I wanted to make a simple Gui but it's not finished, I'll add it when done.
