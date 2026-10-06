module.exports = function (api) {
  api.cache(true);
  return {
    presets: [
      [
        require.resolve('babel-preset-expo', {
          paths: [require('path').dirname(require.resolve('expo/package.json'))],
        }),
        {
          unstable_transformProfile: 'default',
        },
      ],
    ],
  };
};
