package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/StanleySweet/pynab/internal/configd"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	log.SetPrefix("configd: ")

	dbPath := configd.DBPath()
	sockPath := configd.SocketPath()

	db, err := configd.Open(dbPath)
	if err != nil {
		log.Fatalf("db: %v", err)
	}
	defer db.Close()

	svr := configd.New(db, sockPath)
	if err := svr.Start(); err != nil {
		log.Fatalf("start: %v", err)
	}
	defer svr.Close()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sig
		log.Print("shutting down")
		svr.Close()
		os.Exit(0)
	}()

	log.Fatal(svr.Serve())
}
