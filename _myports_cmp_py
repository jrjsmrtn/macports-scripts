#!/usr/bin/env gawk -f
$1~/^py[0-9]*-/ {
    n=split($1, chunks, "-")
    version=chunks[1]
    port = chunks[2]
    if (n>2) {
        for (i=3;i<=n;i++) {
            port=port"-"chunks[i]
        }
    }
    ports[port][version]="*"
    versions[version]++
}
END {
    OFS="\t"
    # TODO sort versions by py, py27, ..., py39, py310
    for(version in versions) {
        header=header"\t"version
    }
    print header

    # TODO sort portnames
    for(port in ports){
        line=port
        for(version in versions){
            line=line"\t"ports[port][version]
        };
        print line
    }
}
