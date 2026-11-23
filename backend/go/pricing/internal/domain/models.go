// Package domain prices a single job from immutable tariff and route inputs.
package domain

type Route struct {
	DistanceKM  string `json:"distance_km"`
	DurationMin string `json:"duration_min"`
	Source      string `json:"source"`
}

type Work struct {
	WeightT            string   `json:"weight_t"`
	VolumeM3           *string  `json:"volume_m3"`
	LoadingMin         string   `json:"loading_min"`
	UnloadingMin       string   `json:"unloading_min"`
	WaitingMin         string   `json:"waiting_min"`
	AdditionalServices []string `json:"additional_services_uzs"`
}

type EmptyRun struct {
	DistanceKM  string `json:"distance_km"`
	DurationMin string `json:"duration_min"`
}

type Rates struct {
	FuelPerLiter     string `json:"fuel_uzs_per_liter"`
	LoadedLiters     string `json:"loaded_liters_per_100_km"`
	EmptyLiters      string `json:"empty_liters_per_100_km"`
	OperationPerKM   string `json:"operation_uzs_per_km"`
	DrivingPerHour   string `json:"driving_uzs_per_hour"`
	LoadingPerHour   string `json:"loading_uzs_per_hour"`
	UnloadingPerHour string `json:"unloading_uzs_per_hour"`
	WaitingPerHour   string `json:"waiting_uzs_per_hour"`
	HandlingPerTon   string `json:"handling_uzs_per_ton"`
	HandlingPerM3    string `json:"handling_uzs_per_m3"`
}

type Bounds struct {
	Minimum string `json:"minimum"`
	Maximum string `json:"maximum"`
}

type Rules struct {
	MinimumPrice     string `json:"minimum_price_uzs"`
	TargetMargin     string `json:"target_margin_uzs"`
	MinimumNetMargin string `json:"minimum_net_margin_uzs"`
	CommissionRate   string `json:"commission_rate"`
	RouteBounds      Bounds `json:"route_bounds"`
	DemandBounds     Bounds `json:"demand_bounds"`
}

type Profile struct {
	TruckTypeID        int64     `json:"truck_type_id"`
	TariffVersionID    int64     `json:"tariff_version_id"`
	MaxWeightT         string    `json:"max_weight_t"`
	MaxVolumeM3        string    `json:"max_volume_m3"`
	Costs              Rates     `json:"costs"`
	Rules              Rules     `json:"rules"`
	ConfiguredEmptyRun *EmptyRun `json:"configured_empty_run"`
}

type Request struct {
	Profile          Profile   `json:"profile"`
	Route            Route     `json:"route"`
	Work             Work      `json:"work"`
	RegionalFactor   *string   `json:"regional_factor"`
	DemandSignal     *string   `json:"demand_signal"`
	ObservedEmptyRun *EmptyRun `json:"observed_empty_run"`
}

type Costs struct {
	Fuel               string `json:"fuel"`
	Operation          string `json:"operation"`
	DriverTime         string `json:"driver_time"`
	Loading            string `json:"loading"`
	Unloading          string `json:"unloading"`
	Waiting            string `json:"waiting"`
	EmptyRun           string `json:"empty_run"`
	AdditionalServices string `json:"additional_services"`
	Total              string `json:"total"`
}

type Result struct {
	TruckTypeID           int64  `json:"truck_type_id"`
	TariffVersionID       int64  `json:"tariff_version_id"`
	Costs                 Costs  `json:"costs"`
	RouteFactor           string `json:"route_factor"`
	DemandFactor          string `json:"demand_factor"`
	EmptyRunSource        string `json:"empty_run_source"`
	PriceBeforeGuardrails string `json:"price_before_guardrails"`
	MinimumPrice          string `json:"minimum_price"`
	MarginFloor           string `json:"margin_floor"`
	RecommendedPrice      string `json:"recommended_price"`
	ExpectedCommission    string `json:"expected_commission"`
	ExpectedNetMargin     string `json:"expected_net_margin"`
}
