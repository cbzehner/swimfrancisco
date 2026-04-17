{ pkgs, lib, config, inputs, ... }:

{
  packages = [
    pkgs.git
    pkgs.zola
  ];

  languages.python.enable = true;
  languages.python.uv.enable = true;

  languages.javascript.enable = true;
  languages.javascript.npm.enable = true;
}
