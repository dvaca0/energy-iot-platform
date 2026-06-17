export const MOCK = {
  nodes: [
    { id:'N001', name:'Node 001', status:'online', ip:'100.64.1.10', building:'FIME', campus:'Colima',
      voltage:228.4, current:18.7, power:4.21, energy_today:31.2, pf:0.93, freq:60.02,
      last_sync:'hace 2 min', buffer:0, samples:8640, rpi_status:'ok', shelly_status:'ok', fw:'1.4.2' },
    { id:'N002', name:'Node 002', status:'online', ip:'100.64.1.11', building:'Laboratorio de Redes', campus:'Colima',
      voltage:225.1, current:12.3, power:2.77, energy_today:19.8, pf:0.89, freq:59.97,
      last_sync:'hace 5 min', buffer:3, samples:6210, rpi_status:'ok', shelly_status:'ok', fw:'1.4.2' }
  ],
  buildings: [
    { id:'B01', name:'FIME', faculty:'Ing. Mecánica y Eléctrica', campus:'Colima', node:'N001',
      status:'normal', power:4.21, energy_week:221.4, cost_week:5312, cost_today:862, anomaly:false, last_update:'2 min' },
    { id:'B02', name:'Laboratorio de Redes', faculty:'Ing. en Sistemas', campus:'Colima', node:'N002',
      status:'warning', power:2.77, energy_week:148.6, cost_week:3566, cost_today:511, anomaly:true, last_update:'5 min' },
    { id:'B03', name:'Rectoría', faculty:'Administración', campus:'Colima', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B04', name:'Biblioteca Central', faculty:'Servicios Escolares', campus:'Colima', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B05', name:'Facultad de Ingeniería', faculty:'Ingeniería', campus:'Coquimatlán', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B06', name:'Data Center', faculty:'TI', campus:'Colima', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B07', name:'Laboratorio de Química', faculty:'Ciencias', campus:'Tecomán', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' },
    { id:'B08', name:'Centro de Cómputo', faculty:'Ing. en Sistemas', campus:'Colima', node:null,
      status:'offline', power:0, energy_week:0, cost_week:0, cost_today:0, anomaly:false, last_update:'—' }
  ],
  hourly: [
    {h:'00:00',kwh:2.1,cost:42,tariff:'base'},{h:'01:00',kwh:1.8,cost:36,tariff:'base'},
    {h:'02:00',kwh:1.6,cost:32,tariff:'base'},{h:'03:00',kwh:1.5,cost:30,tariff:'base'},
    {h:'04:00',kwh:1.7,cost:34,tariff:'base'},{h:'05:00',kwh:1.9,cost:38,tariff:'base'},
    {h:'06:00',kwh:2.8,cost:67,tariff:'intermedia'},{h:'07:00',kwh:4.1,cost:98,tariff:'intermedia'},
    {h:'08:00',kwh:5.8,cost:139,tariff:'intermedia'},{h:'09:00',kwh:6.9,cost:248,tariff:'punta'},
    {h:'10:00',kwh:7.4,cost:266,tariff:'punta'},{h:'11:00',kwh:7.8,cost:280,tariff:'punta'},
    {h:'12:00',kwh:8.1,cost:291,tariff:'punta'},{h:'13:00',kwh:7.6,cost:273,tariff:'punta'},
    {h:'14:00',kwh:6.2,cost:149,tariff:'intermedia'},{h:'15:00',kwh:5.9,cost:142,tariff:'intermedia'},
    {h:'16:00',kwh:6.4,cost:230,tariff:'punta'},{h:'17:00',kwh:7.1,cost:255,tariff:'punta'},
    {h:'18:00',kwh:5.8,cost:139,tariff:'intermedia'},{h:'19:00',kwh:4.6,cost:110,tariff:'intermedia'},
    {h:'20:00',kwh:3.9,cost:94,tariff:'intermedia'},{h:'21:00',kwh:3.2,cost:77,tariff:'intermedia'},
    {h:'22:00',kwh:2.8,cost:56,tariff:'base'},{h:'23:00',kwh:2.3,cost:46,tariff:'base'}
  ],
  weeklyTrend: [
    {day:'Lun',cost:3210,kwh:142},{day:'Mar',cost:3480,kwh:155},{day:'Mié',cost:3290,kwh:146},
    {day:'Jue',cost:3650,kwh:162},{day:'Vie',cost:3820,kwh:169},{day:'Sáb',cost:2100,kwh:93},
    {day:'Dom',cost:1420,kwh:63}
  ],
  forecast: [
    {day:'Sem 1',actual:20900,pred:20900,lower:19500,upper:22300},
    {day:'Sem 2',actual:21400,pred:21200,lower:19800,upper:22600},
    {day:'Sem 3',actual:null,pred:22100,lower:20500,upper:23700},
    {day:'Sem 4',actual:null,pred:22800,lower:21000,upper:24600}
  ],
  anomalies: [
    { id:'A01', time:'03:47', building:'Lab. de Redes', type:'Consumo nocturno anómalo', severity:'warning', value:'2.4 kW', expected:'0.8 kW' },
    { id:'A02', time:'11:23', building:'FIME', type:'Factor de potencia bajo', severity:'info', value:'0.71 FP', expected:'>0.90 FP' },
    { id:'A03', time:'09:05', building:'Lab. de Redes', type:'Pico de demanda', severity:'critical', value:'6.8 kW', expected:'4.5 kW' }
  ],
  recommendations: [
    { id:'R01', building:'FIME', priority:'alta', savings:3250, title:'Reducir consumo en hora punta', desc:'Mover cargas no críticas fuera del periodo 09:00–13:00 y 16:00–18:00 puede reducir el costo estimado mensual.', action:'Revisar equipos encendidos en punta' },
    { id:'R02', building:'Lab. de Redes', priority:'alta', savings:1840, title:'Corregir factor de potencia', desc:'FP promedio de 0.89 genera penalización tarifaria. Se recomienda instalar banco de capacitores.', action:'Solicitar diagnóstico eléctrico' },
    { id:'R03', building:'Lab. de Redes', priority:'media', savings:720, title:'Reducir baseload nocturno', desc:'Se detectó consumo anómalo entre 02:00–05:00. Revisar equipos que permanecen encendidos.', action:'Auditoría nocturna de equipos' }
  ],
  deployments: [
    { id:'D01', node:'N001', building:'FIME', campus:'Colima', panel:'Tablero Principal', tech:'Ing. Ramírez',
      start:'2025-01-06', end:'2025-01-13', progress:71, samples:8640, completeness:98, status:'active', notes:'Instalación sin incidentes.' },
    { id:'D02', node:'N002', building:'Lab. de Redes', campus:'Colima', panel:'Tablero Red A', tech:'Ing. López',
      start:'2025-01-06', end:'2025-01-13', progress:71, samples:6210, completeness:72, status:'active', notes:'Buffer acumulado por corte de internet 3h.' },
    { id:'D03', node:'N001', building:'Rectoría', campus:'Colima', panel:'Tablero General', tech:'Ing. Ramírez',
      start:'2024-12-16', end:'2024-12-23', progress:100, samples:10080, completeness:100, status:'completed', notes:'Despliegue exitoso.' },
    { id:'D04', node:'N002', building:'Biblioteca', campus:'Colima', panel:'Tablero Piso 1', tech:'Ing. López',
      start:'2024-12-16', end:'2024-12-23', progress:100, samples:9870, completeness:98, status:'completed', notes:'Datos completos.' }
  ],
  campuses: [
    { name:'Campus Colima', buildings:6, monitored:2, power:6.98, kwh_week:370, cost_week:8878, status:'active' },
    { name:'Campus Coquimatlán', buildings:1, monitored:0, power:0, kwh_week:0, cost_week:0, status:'inactive' },
    { name:'Campus Tecomán', buildings:1, monitored:0, power:0, kwh_week:0, cost_week:0, status:'inactive' }
  ],
  chatHistory: [
    { role:'assistant', msg:'Hola. Soy el Asistente de Energía IA. Puedes preguntarme sobre costos, consumo, anomalías o comparaciones entre edificios.' }
  ],
  chatResponses: {
    'costo':     'Esta semana, **FIME** es el edificio más costoso con **$5,312 MXN** estimados. Le sigue Lab. de Redes con $3,566 MXN. El costo semanal total estimado del campus es de **$8,878 MXN**.',
    'semana':    'El costo estimado de esta semana hasta hoy es de **$8,878 MXN**. El jueves y viernes son los días de mayor consumo. Se proyecta un mes completo de aproximadamente **$38,400 MXN** si el patrón se mantiene.',
    'anomal':    'Se detectaron **3 anomalías** hoy: un consumo nocturno anómalo en Lab. de Redes a las 03:47 (2.4 kW vs 0.8 kW esperado), un factor de potencia bajo en FIME (0.71) y un pico de demanda en Lab. de Redes a las 09:05.',
    'punta':     'El periodo de punta (09:00–13:00 y 16:00–18:00) representa solo el **23% del tiempo** pero genera el **39% del costo estimado**. Desplazar cargas a periodo base podría ahorrar hasta **$3,250 MXN/mes**.',
    'ahorro':    'Recomendaciones actuales: (1) Reducir punta: $3,250 MXN/mes. (2) Corregir FP en Lab. de Redes: $1,840 MXN/mes. (3) Eliminar baseload nocturno: $720 MXN/mes. **Ahorro potencial total: $5,810 MXN/mes**.',
    'default':   'Puedo ayudarte con información sobre costos, anomalías, periodos tarifarios, proyecciones y comparaciones entre edificios. ¿Qué deseas saber?'
  }
};
