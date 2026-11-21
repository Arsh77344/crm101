'use client';

// Where Indian cities are, so an order can be put on a map. These are plain
// coordinates, not anyone's artwork: the map is drawn from them rather than
// from a borrowed image. A city not listed here is still counted — it just
// shows in the list beside the map instead of as a dot on it.
export const CITIES = {
  delhi: [28.61, 77.21], 'new delhi': [28.61, 77.21], noida: [28.54, 77.39],
  gurgaon: [28.46, 77.03], gurugram: [28.46, 77.03], faridabad: [28.41, 77.32],
  ghaziabad: [28.67, 77.44],
  mumbai: [19.08, 72.88], thane: [19.22, 72.98], 'navi mumbai': [19.03, 73.03],
  pune: [18.52, 73.86], nashik: [19.99, 73.79], nagpur: [21.15, 79.09],
  bengaluru: [12.97, 77.59], bangalore: [12.97, 77.59], mysuru: [12.30, 76.64],
  mysore: [12.30, 76.64], mangaluru: [12.91, 74.86],
  chennai: [13.08, 80.27], coimbatore: [11.02, 76.96], madurai: [9.93, 78.12],
  kolkata: [22.57, 88.36], howrah: [22.59, 88.31], siliguri: [26.73, 88.40],
  hyderabad: [17.39, 78.49], secunderabad: [17.44, 78.50], visakhapatnam: [17.69, 83.22],
  ahmedabad: [23.03, 72.58], surat: [21.17, 72.83], vadodara: [22.31, 73.18],
  rajkot: [22.30, 70.80],
  jaipur: [26.91, 75.79], jodhpur: [26.24, 73.02], udaipur: [24.58, 73.71],
  lucknow: [26.85, 80.95], varanasi: [25.32, 82.97], kanpur: [26.45, 80.33],
  agra: [27.18, 78.01], prayagraj: [25.44, 81.85], allahabad: [25.44, 81.85],
  patna: [25.59, 85.14], ranchi: [23.34, 85.31], jamshedpur: [22.80, 86.18],
  bhubaneswar: [20.30, 85.82], raipur: [21.25, 81.63],
  indore: [22.72, 75.86], bhopal: [23.26, 77.41], gwalior: [26.22, 78.18],
  chandigarh: [30.73, 76.78], ludhiana: [30.90, 75.86], amritsar: [31.63, 74.87],
  jalandhar: [31.33, 75.58],
  dehradun: [30.32, 78.03], shimla: [31.10, 77.17], jammu: [32.73, 74.87],
  srinagar: [34.08, 74.80],
  kochi: [9.93, 76.27], cochin: [9.93, 76.27], thiruvananthapuram: [8.52, 76.94],
  kozhikode: [11.26, 75.78],
  guwahati: [26.14, 91.74], shillong: [25.57, 91.88], imphal: [24.82, 93.94],
  gangtok: [27.33, 88.61], agartala: [23.83, 91.28],
  panaji: [15.49, 73.83], goa: [15.30, 74.08], margao: [15.27, 73.96],
  puducherry: [11.94, 79.83], pondicherry: [11.94, 79.83],
};

// A state's rough middle, for an order that gave a state but no city we know.
export const STATES = {
  'uttar pradesh': [26.85, 80.95], maharashtra: [19.75, 75.71], karnataka: [15.32, 75.71],
  'tamil nadu': [11.13, 78.66], 'west bengal': [22.99, 87.85], gujarat: [22.26, 71.19],
  rajasthan: [27.02, 74.22], delhi: [28.61, 77.21], telangana: [17.12, 79.21],
  'andhra pradesh': [15.91, 79.74], kerala: [10.85, 76.27], punjab: [31.15, 75.34],
  haryana: [29.06, 76.09], bihar: [25.10, 85.31], odisha: [20.95, 85.10],
  'madhya pradesh': [22.97, 78.66], assam: [26.20, 92.94], jharkhand: [23.61, 85.28],
  chhattisgarh: [21.28, 81.87], uttarakhand: [30.07, 79.02], 'himachal pradesh': [31.10, 77.17],
  goa: [15.30, 74.08], 'jammu and kashmir': [33.78, 76.58], chandigarh: [30.73, 76.78],
  puducherry: [11.94, 79.83], manipur: [24.66, 93.91], meghalaya: [25.47, 91.37],
  tripura: [23.94, 91.99], nagaland: [26.16, 94.56], sikkim: [27.53, 88.51],
  'arunachal pradesh': [28.22, 94.73], mizoram: [23.16, 92.94],
};

const key = (s) => String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');

// A city first, then the state it is in, then nothing. Returning null is the
// honest answer for a place we cannot put on a map, and the caller says so.
export function locate(city, state) {
  const c = CITIES[key(city)];
  if (c) return { at: c, how: 'city' };
  const s = STATES[key(state)];
  if (s) return { at: s, how: 'state' };
  return null;
}

// India sits inside this box. An equirectangular projection is near enough at
// this scale and needs no library.
export const BOX = { west: 67.5, east: 97.5, south: 6.5, north: 36.5 };

export function project(lat, lon, w, h) {
  const x = ((lon - BOX.west) / (BOX.east - BOX.west)) * w;
  const y = ((BOX.north - lat) / (BOX.north - BOX.south)) * h;
  return [x, y];
}
