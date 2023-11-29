#!/usr/bin/env python3

import sys
import socket
import os
import time
import subprocess
import signal
import argparse
import importlib.util

if importlib.util.find_spec("iob_colors") is not None:
    import iob_colors
else:
    print(
        "Module `iob_colors.py` not found. Please set the `PYTHONPATH` environment variable with the location of this module."
    )
    print("For example: `export PYTHONPATH=<Path to iob-lib>/scripts`")
    sys.exit(1)

DEBUG = False

# Define the client's IP, port and version
# Must match the server's
PORT = 50007  # Use the same port as the server
VERSION = "V0.3"

# user and duration board is needed
USER = os.environ["USER"]
DURATION = "15"  # Default duration is 5 seconds

# List of processes to kill when terminating board_client
proc_list = []

# Variables to store the commands to run
console_command = None
fpga_prog_command = None
simulator_run_command = None


# Print usage and exit
def perror():
    print(
        f"Usage: client.py [grab [duration in seconds] -c [console launch command] [-p [fpga program command] | -s [simulator run command]] | release]"
    )
    print("If -p is given then -c is required. If -s is given then -c is optional.")
    sys.exit(1)


# Function to form a request
def form_request(command):
    #get name of the project directory, that is name of directry two levels up
    directory = os.path.basename(os.path.dirname(os.path.dirname(os.getcwd())))
    request = f"{command} {USER} {DURATION} {directory} {VERSION}"

# Function to send the request
def send_request(request):
    while True:
        # Create a socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)

        # Connect with the server
        try:
            s.connect((HOST, PORT))
        except:
            print(f"{iob_colors.FAIL}Could not connect to server{iob_colors.ENDC}")
            sys.exit(1)

        # Send the request to the server
        s.sendall(request.encode("utf-8"))

        # Receive the response from the server
        response = s.recv(1024).decode()
        s.close()
        print(response)

        # Process the response
        if "ERROR" in response:
            sys.exit(1)

        if "grab" in request and "Failure" in response:
            time_remaining = float(response.split(" ")[-2])
            print(
                f"{iob_colors.WARNING}Trying again in",
                time_remaining,
                f"seconds{iob_colors.ENDC}",
            )
            time.sleep(time_remaining)
        else:
            # If grab is successful, retrieve the console log file
            if "Success" in response and "grabbed by" in response:
                # Assuming the server sends the console log file name
                console_log_file = response.split()[-1]
                # Retrieve the console log file content
                subprocess.run(f"scp {HOST}:{project_directory}/{console_log_file} .", shell=True)
                print(f"Console output saved to {console_log_file}")

            break


# Function to send a request to release the board
def release_board(signal=None, frame=None):
    request = form_request("release")
    send_request(request)


# Exit the program and release the board if -p is given
def exit_program(exit_code):
    # Release the board if -p is given
    if fpga_prog_command:
        release_board()

    sys.exit(exit_code)


# Function to kill all processes from proc_list and exit with error.
def kill_processes(sig=None, frame=None):
    for proc in proc_list:
        # Check if process is still running
        if proc.poll() is None:
            # Gracefully terminate process group (the process and its children)
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                # Wait for process to terminate gracefully
                proc.wait(2)
            except subprocess.TimeoutExpired:
                # Process did not terminate gracefully, kill it
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    # Dont throw an error if the function is called from signal handler
    if sig is None:
        exit_program(1)
    else:
        exit_program(0)


# Function to wait for a process to finish
# If the process times out, kill all other processes
def proc_wait(proc, timeout):
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"{iob_colors.FAIL}Board grab duration expired!{iob_colors.ENDC}")
        kill_processes()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="board_client.py",
        description="TODO Client to grab FPGA board and manage simulation and console processes.",
        epilog="TODO If -p is given then -c is required. If -s is given then -c is optional.",
    )

    # Add command argument with default value
    parser.add_argument(
        "host",
        nargs="?",
        default="localhost",
        help='Host logical name or IP.',
    )

    # Add command argument with default value
    parser.add_argument(
        "command",
        nargs="?",
        default="query",
        help='Command to send to server. Can be "grab", "release" or "query".',
    )

    # Add optional duration argument only available if command=grab
    parser.add_argument(
        "duration",
        nargs="?",
        default=DURATION,
        help="Duration in seconds to grab the board.",
    )

    # Add -s argument
    parser.add_argument(
        "-t",
        "--target",
        default=None,
        help="Target: simulator or board name.",
    )

    # Assign arguments to variables
    global HOST
    HOST = parser.parse_args().host
    command = parser.parse_args().command
    DURATION = parser.parse_args().duration
    target = parser.parse_args().target

    request = form_request(command)
    if DEBUG:
        print(f'{iob_colors.OKBLUE}DEBUG: Request is "{request}"{iob_colors.ENDC}')

    send_request(request)

    if command == "grab":
        # Call `kill_processes()` when termination signals are received
        signal.signal(signal.SIGINT, kill_processes)
        signal.signal(signal.SIGTERM, kill_processes)
    else:
        # End program if command is not "grab"
        sys.exit(0)

    # Launch simulator in the background if -s was given
    sim_proc = None
    if simulator_run_command:
        print(f"{iob_colors.INFO}Running simulator{iob_colors.ENDC}")
        sim_proc = subprocess.Popen(
            simulator_run_command,
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=True,
            start_new_session=True,
        )
        # Add the simulator process to the list of processes to kill
        proc_list.append(sim_proc)

    # Start counting time since start of FPGA programming
    start_time = time.time()

    # Program the FPGA if -p is given and wait
    if fpga_prog_command:
        print(f"{iob_colors.INFO}Programming FPGA{iob_colors.ENDC}")
        fpga_prog_proc = subprocess.Popen(
            fpga_prog_command,
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=True,
            start_new_session=True,
        )
        proc_list.append(fpga_prog_proc)
        proc_wait(fpga_prog_proc, int(DURATION))

    # Update time passed
    remaining_duration = int(DURATION) - (time.time() - start_time)

    # Run console if -c is given and wait
    if console_command:
        # Run console and wait for completion/timeout.
        print(f"{iob_colors.INFO}Running console{iob_colors.ENDC}")
        console_proc = subprocess.Popen(
            console_command,
            stdout=sys.stdout,
            stderr=sys.stderr,
            shell=True,
            start_new_session=True,
        )
        proc_list.append(console_proc)
        proc_wait(console_proc, remaining_duration)

        # Update time passed
        remaining_duration = int(DURATION) - (time.time() - start_time)

    # Wait for simulator to finish
    if simulator_run_command:
        print(f"{iob_colors.INFO}Waiting for simulator to finish{iob_colors.ENDC}")
        proc_wait(sim_proc, remaining_duration)

    exit_program(0)
