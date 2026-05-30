{
  description = "doctest — executable documentation: run YAML specs and generate Markdown tutorials";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        # The engine is a single, self-contained Python module. pyyaml is
        # required; rich is only used by `run --tui` but is bundled so the TUI
        # works out of the box. The specs themselves invoke nix/node/git from
        # the ambient environment, so those are intentionally NOT baked in.
        pythonEnv = pkgs.python3.withPackages (ps: [ ps.pyyaml ps.rich ]);

        # writeShellScriptBin (rather than writeShellApplication) keeps the
        # build dependency-light — no shellcheck check phase — which matters in
        # offline/sandboxed builds. The wrapper just dispatches to the pinned
        # Python interpreter with the engine module.
        doctest = pkgs.writeShellScriptBin "doctest" ''
          exec ${pythonEnv}/bin/python3 ${./doctest.py} "$@"
        '';
      in
      {
        packages = {
          default = doctest;
          doctest = doctest;
        };

        apps = {
          default = {
            type = "app";
            program = "${doctest}/bin/doctest";
          };
          doctest = {
            type = "app";
            program = "${doctest}/bin/doctest";
          };
        };

        devShells.default = pkgs.mkShell {
          packages = [ pythonEnv ];
        };
      });
}
