GOOS?=linux
GOARCH?=arm
GOARM?=7

.PHONY: configd configd-armhf configd-clean configd-deploy

configd-armhf:
	GOOS=$(GOOS) GOARCH=$(GOARCH) GOARM=$(GOARM) go build -o bin/configd ./cmd/configd/
	@echo "built: bin/configd ($$(file bin/configd | sed 's/.*: //'))"

configd-host:
	go build -o bin/configd-darwin ./cmd/configd/
	@echo "built: bin/configd-darwin"

configd-clean:
	rm -f bin/configd bin/configd-darwin

configd-deploy: configd-armhf
	scp bin/configd $(PYNAB_HOST):/tmp/configd
	ssh $(PYNAB_HOST) "sudo mv /tmp/configd /usr/local/bin/configd && sudo chmod +x /usr/local/bin/configd"
	ssh $(PYNAB_HOST) "sudo cp /opt/pynab/cmd/configd/configd.service /etc/systemd/system/configd.service"
	ssh $(PYNAB_HOST) "sudo systemctl daemon-reload && sudo systemctl enable configd && sudo systemctl restart configd"
	@echo "configd deployed and started"
