rule ReverseShell {
    meta:
        description = "Common reverse shell patterns"
        severity = "critical"
    strings:
        $s1 = "bash -i >& /dev/tcp" ascii
        $s2 = "bash -i >& /dev/udp" ascii
        $s3 = "nc -e /bin/sh" ascii nocase
        $s4 = "nc -e /bin/bash" ascii nocase
        $s5 = "ncat -e /bin/sh" ascii nocase
        $s6 = "rm /tmp/f;mkfifo" ascii
        $s7 = "python -c 'import socket,subprocess" ascii
        $s8 = "perl -e 'use Socket" ascii
    condition:
        any of them
}

rule SSHKeyInjection {
    meta:
        description = "SSH authorized_keys injection via shell"
        severity = "high"
    strings:
        $target = "authorized_keys" ascii
        $method1 = "echo" ascii
        $method2 = ">>" ascii
        $method3 = "curl" ascii
        $method4 = "wget" ascii
    condition:
        $target and (($method1 and $method2) or $method3 or $method4)
}
