import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { motion } from 'framer-motion';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { mapAPI } from '../services/api';
import EmptyState from '../components/EmptyState';
import { Loader2, ExternalLink, LocateFixed } from 'lucide-react';

// Fix leaflet marker icons
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const customIcon = new L.Icon({
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

const myLocationIcon = new L.Icon({
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
  iconSize: [20, 32],
  iconAnchor: [10, 32],
  popupAnchor: [1, -28],
  shadowSize: [32, 32],
  className: 'hue-rotate-[200deg]',
});

// Component that handles flyTo commands imperatively
function MapController({ flyTo }) {
  const map = useMap();
  const didFly = useRef(false);
  useEffect(() => {
    if (flyTo && !didFly.current) {
      map.flyTo(flyTo, 12, { duration: 1.2 });
      didFly.current = true;
    }
  }, [map, flyTo]);
  return null;
}

export default function MapPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [mapItems, setMapItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [myLocation, setMyLocation] = useState(null);
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState('');
  const [flyToTarget, setFlyToTarget] = useState(null);

  useEffect(() => {
    fetchMapItems();
  }, []);

  // Parse ?flyTo=lat,lng from URL
  useEffect(() => {
    const flyToParam = searchParams.get('flyTo');
    if (flyToParam) {
      const parts = flyToParam.split(',').map(Number);
      if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        setFlyToTarget(parts);
      }
    }
  }, [searchParams]);

  const fetchMapItems = async () => {
    try {
      const { data } = await mapAPI.getItems();
      setMapItems(data.items || []);
    } catch (err) {
      console.error('Failed to fetch map items:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleMyLocation = () => {
    if (!navigator.geolocation) {
      setLocateError('Geolocation not supported by your browser.');
      return;
    }
    setLocating(true);
    setLocateError('');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const coords = [pos.coords.latitude, pos.coords.longitude];
        setMyLocation(coords);
        setFlyToTarget(coords);
        setLocating(false);
      },
      (err) => {
        setLocateError('Could not get location: ' + err.message);
        setLocating(false);
      },
      { timeout: 10000 }
    );
  };

  // Collect all markers
  const markers = [];
  mapItems.forEach(item => {
    (item.places || []).forEach(place => {
      if (place.latitude && place.longitude) {
        markers.push({ ...place, item });
      }
    });
  });

  // Determine initial center: flyTo target → markers average → world
  const initialCenter = flyToTarget || (markers.length > 0
    ? [
        markers.reduce((s, m) => s + m.latitude, 0) / markers.length,
        markers.reduce((s, m) => s + m.longitude, 0) / markers.length
      ]
    : [20, 0]);

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 text-brand animate-spin" />
    </div>
  );

  return (
    <div data-testid="map-page">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <div className="flex items-center justify-between mb-6">
          <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-text-primary">Map View</h1>
          <button
            onClick={handleMyLocation}
            disabled={locating}
            data-testid="my-location-button"
            className="flex items-center gap-2 px-4 py-2 rounded-full border border-border-default bg-white text-sm font-medium text-text-primary hover:border-brand hover:text-brand transition-all disabled:opacity-50"
          >
            {locating
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <LocateFixed className="w-4 h-4" />
            }
            My Location
          </button>
        </div>

        {locateError && (
          <p className="text-xs text-red-500 mb-3">{locateError}</p>
        )}

        {markers.length === 0 ? (
          <EmptyState
            title="No places on the map"
            message="Save content with places or locations mentioned to see them here."
          />
        ) : (
          <div className="rounded-2xl overflow-hidden border border-border-default shadow-sm" style={{ height: '70vh' }} data-testid="map-container">
            <MapContainer
              center={initialCenter}
              zoom={flyToTarget ? 12 : (markers.length === 1 ? 10 : 3)}
              style={{ height: '100%', width: '100%' }}
              scrollWheelZoom={true}
            >
              <TileLayer
                attribution='&copy; <a href="https://osm.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
              <MapController flyTo={flyToTarget} />
              {markers.map((marker, idx) => (
                <Marker
                  key={`${marker.item.id}-${idx}`}
                  position={[marker.latitude, marker.longitude]}
                  icon={customIcon}
                >
                  <Popup>
                    <div className="font-body text-sm max-w-48">
                      <p className="font-semibold text-text-primary mb-1">{marker.name}</p>
                      <p className="text-text-secondary text-xs mb-2">{marker.item.title}</p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => navigate(`/items/${marker.item.id}`)}
                          className="text-brand text-xs hover:underline"
                        >
                          View Item
                        </button>
                        <a href={marker.item.url} target="_blank" rel="noopener noreferrer"
                          className="text-brand text-xs hover:underline flex items-center gap-1">
                          Source <ExternalLink className="w-3 h-3" />
                        </a>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              ))}
              {myLocation && (
                <Marker position={myLocation} icon={myLocationIcon}>
                  <Popup>
                    <p className="text-sm font-semibold">You are here</p>
                  </Popup>
                </Marker>
              )}
            </MapContainer>
          </div>
        )}

        {/* Items list below map */}
        {markers.length > 0 && (
          <div className="mt-6">
            <h2 className="text-sm uppercase tracking-wider font-semibold text-text-secondary mb-3">
              {mapItems.length} place-related items
            </h2>
            <div className="space-y-2">
              {mapItems.map(item => (
                <div
                  key={item.id}
                  onClick={() => navigate(`/items/${item.id}`)}
                  className="bg-white border border-border-default rounded-xl p-4 cursor-pointer hover:border-sage transition-colors flex items-center gap-4"
                  data-testid={`map-item-${item.id}`}
                >
                  <div className="flex-1">
                    <p className="font-medium text-text-primary text-sm">{item.title}</p>
                    <div className="flex items-center gap-2 mt-1">
                      {(item.places || []).map(p => (
                        <span key={p.id} className="text-xs text-text-secondary flex items-center gap-1">
                          <span className="w-1.5 h-1.5 bg-brand rounded-full" />{p.name}
                        </span>
                      ))}
                    </div>
                  </div>
                  <span className="text-xs text-text-secondary">{item.category}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </motion.div>
    </div>
  );
}
