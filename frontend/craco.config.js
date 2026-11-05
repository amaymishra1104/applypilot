// craco.config.js
const path = require("path");
require("dotenv").config();

module.exports = {
  eslint: {
    configure: {
      extends: ["plugin:react-hooks/recommended"],
      rules: {
        "react-hooks/rules-of-hooks": "error",
        "react-hooks/exhaustive-deps": "warn",
      },
    },
  },
  webpack: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
    configure: (webpackConfig) => {
      webpackConfig.watchOptions = {
        ...webpackConfig.watchOptions,
        ignored: [
          "**/node_modules/**",
          "**/.git/**",
          "**/build/**",
          "**/dist/**",
          "**/coverage/**",
          "**/public/**",
        ],
      };
      return webpackConfig;
    },
  },
  devServer: (devServerConfig) => {
    delete devServerConfig.onAfterSetupMiddleware;
    delete devServerConfig.onBeforeSetupMiddleware;
    if (devServerConfig.https !== undefined) {
      if (devServerConfig.https) {
        devServerConfig.server = "https";
      }
      delete devServerConfig.https;
    }
    devServerConfig.setupMiddlewares = (middlewares, devServer) => {
      return middlewares;
    };
    return devServerConfig;
  },
};
