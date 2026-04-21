(function(global) {
    const SENSOR_DEFS = global.__SENSOR_DEFS__ || {};

    const SENSOR_ORDER = Object.keys(SENSOR_DEFS);

    function getSensorDef(sensorName) {
        return SENSOR_DEFS[sensorName] || null;
    }

    function getSensorNames() {
        return SENSOR_ORDER.slice();
    }

    function hasSensor(sensorName) {
        return Object.prototype.hasOwnProperty.call(SENSOR_DEFS, sensorName);
    }

    function shouldShowNodeTopic(sensorName) {
        const def = getSensorDef(sensorName);
        return Boolean(def && def.showNodeTopic);
    }

    function detectAvailability(items, patterns) {
        if (!Array.isArray(items) || items.length === 0 || !Array.isArray(patterns) || patterns.length === 0) {
            return null;
        }

        return items.some(item =>
            patterns.some(pattern => item.toLowerCase().includes(pattern.toLowerCase()))
        );
    }

    function resolveNodeAvailable(sensorName, ros2NodesCache, fallbackValue) {
        if (!shouldShowNodeTopic(sensorName)) {
            return null;
        }

        const def = getSensorDef(sensorName);
        const detected = detectAvailability(ros2NodesCache, def ? def.nodePatterns : []);
        return detected !== null ? detected : fallbackValue === true;
    }

    function resolveTopicAvailable(sensorName, ros2TopicsCache, fallbackValue) {
        if (!shouldShowNodeTopic(sensorName)) {
            return null;
        }

        const def = getSensorDef(sensorName);
        const detected = detectAvailability(ros2TopicsCache, def ? def.topicPatterns : []);
        return detected !== null ? detected : fallbackValue === true;
    }

    global.SensorCatalog = {
        defs: SENSOR_DEFS,
        get: getSensorDef,
        getNames: getSensorNames,
        has: hasSensor,
        shouldShowNodeTopic,
        resolveNodeAvailable,
        resolveTopicAvailable,
    };
})(window);
