var hidden, visibilityChange, getVolumeVar;

if (typeof document.hidden !== "undefined") { // Opera 12.10 and Firefox 18 and later support
  hidden = "hidden";
  visibilityChange = "visibilitychange";
} else if (typeof document.msHidden !== "undefined") {
  hidden = "msHidden";
  visibilityChange = "msvisibilitychange";
} else if (typeof document.webkitHidden !== "undefined") {
  hidden = "webkitHidden";
  visibilityChange = "webkitvisibilitychange";
}


	function meterInit(){

    	$.ajax({
        	url: "/getConfig",
        	dataType: "json"
    		}).success(function(data) {
    			window.soundThreshold = data['soundThreshold'];
 		   }).error(function() {
    	});

    	console.log(window.soundThreshold);

    	var vuMeter = document.getElementById('vuMeter');
    	//vuMeter.optimum = window.soundThreshold;
    	//vuMeter.low = (10 - window.soundThreshold)/2;

    	getVolumeVar = setInterval(function(){
            getVolume();
    	}, 500);

	}

  function handleVisibilityChange() {
    if (document[hidden]) {
      clearInterval(getVolumeVar);
    } else {
      clearInterval(getVolumeVar);
      getVolumeVar = setInterval(function(){
            getVolume();
    	}, 500);
    }
  }


    function getVolume(){

    	$.ajax({
        	url: "/getConfig",
        	dataType: "json"
    		}).success(function(data) {
    			window.soundThreshold = data['soundThreshold'];
    			window.soundSensitivity = data['soundSensitivity'];
    		}).error(function() {
    	});

    	// In time, the following will need to come from settings
    	max_sensitivity = window.soundSensitivity/4;

    	$.getJSON('/js/vol_data.json', function(vol_data){

    		var ratio = 10/max_sensitivity;
    		var meter_value = ratio * (max_sensitivity + vol_data['peak']);
    		if (meter_value < 0) { meter_value = 0; }
    		document.getElementById('vuMeter').value = meter_value;

    		var vid = document.getElementById('remotevideo');

    		if (meter_value < window.soundThreshold) { vid.muted = true; }
    		if (meter_value >= window.soundThreshold) { vid.muted = false; }

    	});


    }

    $( document ).ready(function(){
      //document.addEventListener(visibilityChange, handleVisibilityChange, false);
      meterInit();

    });
