// Runs explicit gear swaps through WoWSims' native bulk API.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"runtime"

	"github.com/wowsims/forever/sim"
	"github.com/wowsims/forever/sim/core/bulk"
	"github.com/wowsims/forever/sim/core/proto"
	"google.golang.org/protobuf/encoding/protojson"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	requestPath := flag.String("request", "", "BulkSimRequest JSON")
	output := flag.String("out", "bulk-result.json", "BulkSimResult JSON")
	workers := flag.Int("workers", 4, "CPU limit, 1 to 4")
	flag.Parse()
	if *workers < 1 || *workers > 4 {
		return fmt.Errorf("workers must be between 1 and 4")
	}
	runtime.GOMAXPROCS(*workers)
	sim.RegisterAll()
	input, err := os.ReadFile(*requestPath)
	if err != nil {
		return err
	}
	request := &proto.BulkSimRequest{}
	if err := protojson.Unmarshal(input, request); err != nil {
		return err
	}
	if !request.AllResults || len(request.Candidates) == 0 {
		return fmt.Errorf("bridge requires explicit candidates and all_results")
	}
	progress := make(chan *proto.ProgressMetrics, 100)
	go bulk.BulkSimAsync(request, progress, "ret-sim-bridge")
	var result *proto.BulkSimResult
	for update := range progress {
		fmt.Fprintf(os.Stderr, "Bulk progress: %d / %d; stage %s\n", update.CompletedIterations, update.TotalIterations, update.BulkStage.String())
		if update.FinalBulkSimResult != nil {
			result = update.FinalBulkSimResult
		}
	}
	if result == nil {
		return fmt.Errorf("WoWSims returned no bulk result")
	}
	if result.Error != nil && result.Error.Message != "" {
		return fmt.Errorf("WoWSims bulk: %s", result.Error.Message)
	}
	if len(result.TopResults) != len(request.Candidates) {
		return fmt.Errorf("WoWSims returned an incomplete candidate set")
	}
	data, err := protojson.MarshalOptions{EmitUnpopulated: true}.Marshal(result)
	if err != nil {
		return err
	}
	// Keep the engine response intact for inspection and reproducibility.
	var valid any
	if err := json.Unmarshal(data, &valid); err != nil {
		return err
	}
	return os.WriteFile(*output, data, 0644)
}
