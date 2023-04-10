CONFIG_FILES := $(wildcard /reg/g/pcds/pyps/config/*/iocmanager.cfg)
WHATRECORD = /cds/group/pcds/pyps/conda/py39/envs/pcds-5.6.0/bin/whatrecord

all: summary.html

clean:
	rm -f iocs.json summary.html

iocs.json: $(CONFIG_FILES)
	$(WHATRECORD) iocmanager-loader $^ > $@

summary.html: iocs.json summary.tpl.html summary.py
	python summary.py > summary.html

.PHONY: all clean
