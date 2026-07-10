// The app reuses the web client's pure scan-payload grammar
// (client/src/utils/scan.ts) via relative imports. Those files live outside
// this package root, so Metro must be told to watch them.
const { getDefaultConfig } = require("expo/metro-config");
const path = require("path");

const config = getDefaultConfig(__dirname);
config.watchFolders = [path.resolve(__dirname, "..", "client", "src", "utils")];

module.exports = config;
