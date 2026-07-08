import subprocess

BE = "be_http_proxy"

def srv(id: int) -> str:
    return f"srv{id}"

def main():
    _command = f"set server {BE}/{srv(1)} addr 127.0.0.1 port 69"
    _haproxy = "nc 127.0.0.1 9999"
    echo = subprocess.Popen(("echo", _command), stdout=subprocess.PIPE)
    output = subprocess.check_output(_haproxy.split(" "), stdin=echo.stdout)
    echo.communicate()

    print(output)

    return 0

if __name__ == "__main__":
    main()
