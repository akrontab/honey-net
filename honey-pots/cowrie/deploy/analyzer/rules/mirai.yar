rule Mirai {
    meta:
        description = "Mirai botnet family indicators"
        severity = "critical"
    strings:
        $s1 = "/bin/busybox MIRAI" ascii
        $s2 = "LZRD" ascii
        $s3 = "SORA" ascii
        $s4 = "MOZI" ascii
        $s5 = "selfrep" ascii nocase
        $s6 = "scannerv2" ascii nocase
        $s7 = "attack_ongoing" ascii
    condition:
        $s1 or 2 of ($s2, $s3, $s4, $s5, $s6, $s7)
}

rule BotnetC2 {
    meta:
        description = "Generic botnet C2 patterns"
        severity = "high"
    strings:
        $s1 = "kill_ourselves" ascii
        $s2 = "bot_killer" ascii
        $s3 = "hide_process" ascii
        $s4 = "antidebug" ascii nocase
    condition:
        any of them
}
