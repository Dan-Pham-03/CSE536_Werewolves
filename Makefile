.PHONY: help setup run clean test install

help:
	@echo "Werewolves Game - Unix Domain Sockets"
	@echo ""
	@echo "Usage:"
	@echo "  make setup      - Create necessary directories"
	@echo "  make run        - Run the game (default: 4 players, 1 werewolf)"
	@echo "  make run-players NUM=X WEREWOLVES=Y - Run with custom counts"
	@echo "  make clean      - Clean up sockets and logs"
	@echo "  make test       - Run tests"
	@echo "  make install    - Install dependencies"
	@echo ""

setup:
	mkdir -p sockets logs
	@echo "Directories created"

run: setup
	bash bin/run_game.sh 4

run-players: setup
	bash bin/run_game.sh $(NUM) $(WEREWOLVES)

clean:
	bash bin/cleanup.sh
	rm -rf logs/*
	rm -rf sockets/*

test:
	python3 -m pytest tests/ -v

install:
	pip3 install -r requirements.txt

.DEFAULT_GOAL := help
