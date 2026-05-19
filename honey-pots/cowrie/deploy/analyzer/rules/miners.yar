rule XMRig {
    meta:
        description = "XMRig cryptocurrency miner"
        severity = "high"
    strings:
        $s1 = "xmrig" nocase ascii wide
        $s2 = "--donate-level" ascii
        $s3 = "stratum+tcp://" ascii
        $s4 = "stratum+ssl://" ascii
    condition:
        2 of them
}

rule MinerPool {
    meta:
        description = "Known mining pool domains"
        severity = "high"
    strings:
        $p1 = "pool.minexmr.com" ascii nocase
        $p2 = "monerohash.com" ascii nocase
        $p3 = "supportxmr.com" ascii nocase
        $p4 = "hashvault.pro" ascii nocase
        $p5 = "nanopool.org" ascii nocase
        $p6 = "2miners.com" ascii nocase
        $p7 = "gulf.moneroocean.stream" ascii nocase
        $p8 = "xmr-eu1.nanopool.org" ascii nocase
    condition:
        any of them
}
