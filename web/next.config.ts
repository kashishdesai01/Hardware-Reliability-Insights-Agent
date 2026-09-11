import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  webpack: (webpackConfig) => {
    // Vega's Node renderer optionally imports canvas. Charts in HRIA render in
    // the browser, so excluding the native module keeps production builds
    // deterministic without changing chart behavior.
    webpackConfig.resolve.alias.canvas = false;
    return webpackConfig;
  },
};

export default config;
