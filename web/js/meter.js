    function toggleMute(){
    	var vid = document.getElementById('remotevideo');
		vid.muted = !vid.muted;
	}
		
	function meterInit(){
    	
    	setInterval(function(){
            
            getVolume();
    	
    	}, 200);
    	
	}
	
    
    function getVolume(){
    	
    	// In time, the following will need to come from settings
    	var max_sensitivity = 2.5;
    	var noise_cutoff = 0.00;
    	
    	$.getJSON('/js/vol_data.json', function(vol_data){
    		
    		var meter_value = 2.5 + vol_data['peak'];
    		if (meter_value < 0) { meter_value = 0; }
    		document.getElementById('vuMeter').value = meter_value;
    		
    		var vid = document.getElementById('remotevideo');
    		
    		if (meter_value < noise_cutoff) { vid.muted = true; }
    		if (meter_value >= noise_cutoff) { vid.muted = false; }
    	
    	});
    	

    }
    
    $( document ).ready(function(){
    	meterInit();
    
    });
