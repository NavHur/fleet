## Tool output

Codex keeps about 10k tokens of one code-mode script's output and drops the
rest, whatever `max_output_tokens` each command asks for. Print each command's
`output` field as plain text under a one-line header, not the result object:
JSON escapes every newline and adds `chunk_id` and `wall_time` to each one.
Keep one script under about 8k tokens of output; read large files in their own
calls or in `sed -n` ranges rather than batching several `cat`s.
