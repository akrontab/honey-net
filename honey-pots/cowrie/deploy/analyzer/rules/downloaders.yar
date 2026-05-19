rule Dropper {
    meta:
        description = "Script dropper that downloads and executes a payload"
        severity = "medium"
    strings:
        $exec1 = "chmod 777" ascii
        $exec2 = "chmod +x" ascii
        $dl1 = "wget http" ascii nocase
        $dl2 = "curl http" ascii nocase
        $dl3 = "wget -q" ascii nocase
        $dl4 = "curl -s" ascii nocase
        $tmp = "/tmp/" ascii
    condition:
        ($exec1 or $exec2) and ($dl1 or $dl2 or $dl3 or $dl4) and $tmp
}

rule Persistence {
    meta:
        description = "Persistence mechanism via cron or shell profile"
        severity = "high"
    strings:
        $s1 = "crontab -" ascii
        $s2 = "/etc/cron" ascii
        $s3 = "rc.local" ascii
        $s4 = ">> .bashrc" ascii
        $s5 = ">> .bash_profile" ascii
        $s6 = ">> /etc/profile" ascii
    condition:
        any of them
}
