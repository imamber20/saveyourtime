import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { mapAPI } from '../services/api';
import EmptyState from '../components/EmptyState';
import { Loader2, ExternalLink } from 'lucide-react';

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

export default function MapPage() {
  const navigate = useNavigate();
  const [mapItems, setMapItems] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchMapItems();
  }, []);

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

  // Collect all markers
  const markers = [];
  mapItems.forEach(item => {
    (item.places || []).forEach(place => {
      if (place.latitude && place.longitude) {
        markers.push({ ...place, item });
      }
    });
  });

  // Calculate center from markers
  const center = markers.length > 0
    ? [
        markers.reduce((s, m) => s + m.latitude, 0) / markers.length,
        markers.reduce((s, m) => s + m.longitude, 0) / markers.length
      ]
    : [20, 0]; // default world center

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <Loader2 className="w-8 h-8 text-brand animate-spin" />
    </div>
  );

  return (
    <div data-testid="map-page">
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <h1 className="font-heading text-2xl sm:text-3xl font-semibold text-text-primary mb-6">Map View</h1>

        {markers.length === 0 ? (
          <EmptyState
            title="No places on the map"
            message="Save content with places or locations mentioned to see them here."
          />
        ) : (
          <div className="rounded-2xl overflow-hidden border border-border-default shadow-sm" style={{ height: '70vh' }} data-testid="map-container">
            <MapContainer
              center={center}
              zoom={markers.length === 1 ? 10 : 3}
              style={{ height: '100%', width: '100%' }}
              scrollWheelZoom={true}
            >
              <TileLayer
                attribution='&copy; <a href="https://osm.org/copyright">OpenStreetMap</a>'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />
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
