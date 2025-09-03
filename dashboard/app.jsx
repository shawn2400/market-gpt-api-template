import React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

const sampleData = [
  { time: "09:00", pnl: 120 },
  { time: "10:00", pnl: 240 },
  { time: "11:00", pnl: 190 },
  { time: "12:00", pnl: 280 },
  { time: "13:00", pnl: 340 },
];

export default function DashboardApp() {
  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">AlgoGPT Dashboard</h1>
      <Tabs defaultValue="summary">
        <TabsList>
          <TabsTrigger value="summary">Summary</TabsTrigger>
          <TabsTrigger value="pnl">PnL</TabsTrigger>
          <TabsTrigger value="status">Status</TabsTrigger>
        </TabsList>
        <TabsContent value="summary">
          <Card>
            <CardContent className="p-4 space-y-2">
              <p><strong>Version:</strong> 2.17.0</p>
              <p><strong>Trades Today:</strong> 12</p>
              <p><strong>Win Rate:</strong> 66%</p>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="pnl">
          <Card>
            <CardContent className="p-4">
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={sampleData} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="pnl" stroke="#8884d8" activeDot={{ r: 8 }} />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="status">
          <Card>
            <CardContent className="p-4 space-y-2">
              <p><strong>Executor:</strong> Running</p>
              <p><strong>AutoRun:</strong> Enabled</p>
              <p><strong>Open Trades:</strong> 3</p>
              <Button variant="outline">Refresh</Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

