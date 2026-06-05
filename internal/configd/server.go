package configd

import (
	"bufio"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/url"
	"os"
	"strings"
)

type Request struct {
	ID     int            `json:"id"`
	Op     string         `json:"op"`
	Table  string         `json:"table"`
	Data   map[string]any `json:"data,omitempty"`
	Fields []string       `json:"fields,omitempty"`
}

type Response struct {
	ID    int            `json:"id"`
	OK    bool           `json:"ok"`
	Data  map[string]any `json:"data,omitempty"`
	Error string         `json:"error,omitempty"`
}

type Server struct {
	db     *DB
	socket string
	ln     net.Listener
}

func New(db *DB, socket string) *Server {
	return &Server{db: db, socket: socket}
}

func (s *Server) Start() error {
	if err := os.Remove(s.socket); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove socket %s: %w", s.socket, err)
	}
	ln, err := net.Listen("unix", s.socket)
	if err != nil {
		return fmt.Errorf("listen %s: %w", s.socket, err)
	}
	s.ln = ln
	if err := os.Chmod(s.socket, 0666); err != nil {
		return fmt.Errorf("chmod socket: %w", err)
	}
	log.Printf("configd listening on %s", s.socket)
	return nil
}

func (s *Server) Serve() error {
	for {
		conn, err := s.ln.Accept()
		if err != nil {
			return err
		}
		go s.handle(conn)
	}
}

func (s *Server) Close() error {
	return s.ln.Close()
}

func (s *Server) handle(conn net.Conn) {
	defer conn.Close()
	sc := bufio.NewScanner(conn)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var req Request
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			s.write(conn, Response{Error: fmt.Sprintf("bad request: %v", err)})
			return
		}
		resp := s.process(req)
		s.write(conn, resp)
	}
}

func (s *Server) write(conn net.Conn, resp Response) {
	conn.Write([]byte(jsonEncode(resp) + "\n"))
}

func (s *Server) process(req Request) Response {
	switch req.Op {
	case "get":
		return s.handleGet(req)
	case "set":
		return s.handleSet(req)
	default:
		return Response{ID: req.ID, Error: fmt.Sprintf("unknown op: %s", req.Op)}
	}
}

func (s *Server) handleGet(req Request) Response {
	table := tableName(req.Table)
	row, err := s.db.GetRow(table)
	if err != nil {
		return Response{ID: req.ID, Error: err.Error()}
	}
	row = sanitizeRow(row)
	if len(req.Fields) > 0 {
		filtered := make(map[string]any, len(req.Fields))
		for _, f := range req.Fields {
			if v, ok := row[f]; ok {
				filtered[f] = v
			}
		}
		row = filtered
	}
	return Response{ID: req.ID, OK: true, Data: row}
}

func (s *Server) handleSet(req Request) Response {
	if req.Data == nil {
		return Response{ID: req.ID, Error: "no data provided"}
	}
	table := tableName(req.Table)
	if err := s.db.SetFields(table, req.Data); err != nil {
		return Response{ID: req.ID, Error: err.Error()}
	}
	return Response{ID: req.ID, OK: true}
}

func sanitizeRow(row map[string]any) map[string]any {
	out := make(map[string]any, len(row))
	for k, v := range row {
		switch val := v.(type) {
		case []byte:
			out[k] = string(val)
		default:
			out[k] = val
		}
	}
	return out
}

var tableSuffix = map[string]string{
	"nabweatherd":     "nabweatherd_config",
	"nabairqualityd":  "nabairqualityd_config",
	"nabclockd":       "nabclockd_config",
	"nabsurprised":    "nabsurprised_config",
	"nabmastodond":    "nabmastodond_config",
	"nab8balld":       "nab8balld_config",
	"nabttsd":         "nabttsd_config",
	"nabd":            "nabd_config",
}

func tableName(name string) string {
	if strings.Contains(name, "_") {
		return name
	}
	if t, ok := tableSuffix[name]; ok {
		return t
	}
	return name + "_config"
}

func jsonEncode(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

func SocketPath() string {
	if s := os.Getenv("PYNAB_CONFIG_SOCK"); s != "" {
		return s
	}
	return "/tmp/pynab-config.sock"
}

func DBPath() string {
	raw := os.Getenv("PYNAB_DB_PATH")
	if raw != "" {
		expanded := strings.TrimPrefix(raw, "file://")
		if u, err := url.Parse(raw); err == nil && u.Path != "" {
			expanded = u.Path
		}
		return expanded
	}
	return "/opt/pynab/data/pynab.db"
}
