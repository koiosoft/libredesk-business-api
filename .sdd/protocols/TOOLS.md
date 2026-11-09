# Tools Loader

- Silently scan `.sdd/protocols/tools/enabled/` for all `.md` files.
- Read and apply their content as rules during this session.
- Do NOT warn or notify the user if the directory or files are not found. Proceed silently.
- Completely ignore the `disabled/` folder.