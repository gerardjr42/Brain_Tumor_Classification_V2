

import streamlit as st
import tensorflow as tf
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image

import numpy as np
import plotly.graph_objects as go
import cv2

from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout, Flatten
from tensorflow.keras.optimizers import Adamax
from tensorflow.keras.metrics import Precision, Recall
import google.generativeai as genai
import PIL.Image
import os

#Load our Google API KEY to use Gemini
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

#Generate Explanation Prompt
def generate_explanation(img_array, model_prediction, confidence):

  prompt = f"""You are an expert neurologist. You are tasked with explaining a saliency map of the brain tumor MRI scan. The saliency map was generated by a deep learning model that was trained to classify brain tumors as either glioma, meningioma, pituitary, or no tumor.

  The saliency map highlughts the regions of the image that the machine learning model is focusing on to make the prediction.

  The deep learning model predicted the image to be of class '{model_prediction}' with a confidence of {confidence * 100}%.

  In your response:
   - Explain what regions of the brain the model is focusing on, based on the saliency map. Refer to the regions highlighted in light cyan, those are the regions where the model is focusing on.
   - Explain possible reasons why the model made the prediction it did.
   - Don't mention anything like 'The saliency map highlights the regions the model is focusing on, whuch are in light cyan' in your explanation.
   - Keep your explanation to 4 sentences max.

   Let's think step by step about this. Verify step by step.
  """

  img = PIL.Image.fromarray(img_array)

  model = genai.GenerativeModel(model_name="gemini-1.5-flash")
  response = model.generate_content([prompt, img])

  return response.text



#Create Saliency Map
@st.cache_data
def generate_saliency_map(model, img_array, class_index, img_size):
  with tf.GradientTape() as tape:
    img_tensor = tf.convert_to_tensor(img_array)
    tape.watch(img_tensor)
    predictions = model(img_tensor)
    target_class = predictions[:, class_index]

  gradients = tape.gradient(target_class, img_tensor)
  gradients = tf.math.abs(gradients)
  gradients = tf.reduce_max(gradients, axis=-1)
  gradients = gradients.numpy().squeeze()

  #Resize gradients to match original image size
  gradients = cv2.resize(gradients, img_size)

  #Create a circular mask for the brain area
  center = (gradients.shape[0] // 2, gradients.shape[1] // 2)
  radius = min(center[0], center[1]) - 10
  y, x = np.ogrid[:gradients.shape[0], :gradients.shape[1]]
  mask = (x - center[0])**2 + (y - center[1])**2 <= radius**2

  #Apply mask to gradients
  gradients = gradients * mask

  #Normalize only the brain area
  brain_gradients = gradients[mask]
  if brain_gradients.max() > brain_gradients.min():
    brain_gradients = (brain_gradients - brain_gradients.min()) / (brain_gradients.max() - brain_gradients.min())
  gradients[mask] = brain_gradients

  #Apply a higher threshold
  threshold = np.percentile(gradients[mask], 80)
  gradients[gradients < threshold] = 0

  #Apply more aggressive smoothing
  gradients = cv2.GaussianBlur(gradients, (11, 11), 0)

  #Create heatmap overlay with enhanced contrast
  heatmap = cv2.applyColorMap(np.uint8(255 * gradients), cv2.COLORMAP_JET)
  heatmap = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)

  #Resize heatmap to match original image size
  heatmap = cv2.resize(heatmap, img_size)

  #Overlay heatmap on original image with increased opacity
  original_img = img_array[0] * 255
  superimposed_img = heatmap * 0.7 + original_img * 0.3
  superimposed_img = superimposed_img.astype(np.uint8)

  return superimposed_img



#Load Xception Model Selected
def load_xception_model():
  img_shape=(299,299,3)
  base_model = tf.keras.applications.Xception(
      weights='imagenet',
      input_shape=img_shape,
      include_top=False,
      pooling='max'
  )
  model = Sequential([
      base_model,
      Flatten(),
      Dropout(rate=0.3),
      Dense(128, activation='relu'),
      Dropout(rate=0.25),
      Dense(4, activation='softmax')
  ])
  model.build((None,) + img_shape)
  model.compile(Adamax(learning_rate=0.001),
                loss='categorical_crossentropy',
                metrics=['accuracy',Precision(),Recall()]
                )
  model.load_weights("xception_model.weights.h5")
  return model


 #Streamlit UI
st.title("Brain Tumor Classification")
st.write("Upload an image of a brain MRI scan to classify.")

#Allow users to upload MRI images to model in streamlit
uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
  selected_model = st.radio(
      "Select Model",
      ("Transfer Learning - Xception", "Custom_CNN")
  )
  #Load user choice of model selected
  if selected_model == "Transfer Learning - Xception":
    model = load_xception_model()
    img_size = (299, 299)
  else:
    model = load_model("cnn_model.h5")
    img_size = (224, 224)

  labels = ['Glioma', 'Meningioma', 'No tumor', 'Pituitary']
  #Process Image
  img = image.load_img(uploaded_file, target_size=img_size)
  img_array = image.img_to_array(img)
  img_array = np.expand_dims(img_array, axis=0)
  img_array /= 255

  prediction = model.predict(img_array)

  class_index = np.argmax(prediction[0])
  result = labels[class_index]

  st.write(f"Predicted Class: {result}")
  st.write("Predictions:")
  for label, prob in zip(labels, prediction[0]):
    st.write(f"{label}: {prob:.4f}")

  #Display saliency map
  saliency_map = generate_saliency_map(model, img_array, class_index, img_size)

  col1, col2 = st.columns(2)
  with col1:
    st.image(uploaded_file, caption='Uploaded MRI', use_container_width=True)
  with col2:
    st.image(saliency_map, caption='Saliency Map', use_container_width=True)


  #Classification Results
  st.write("## Classification Results")

  result_container = st.container()
  result_container.markdown(
      f"""
    <div style="background-color: #000000; color: #ffffff; padding: 30px; border-radius: 15px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div stlye="flex: 1; text-align:center;">
          <h3 stlye="color: #ffffff; margin-bottom: 10px; font-size: 20px;">Predictions</h3>
          <p style="font-size: 36px; font-weight: 800; color: #FF0000; margin: 0;">
            {result}
          </p>
        </div>
        <div style=width:2px; height:80px; background-color: #ffffff; margin: 0 20px;"></div>
        <div style=flex: 1; text-align: center;">
          <h3 style="color: #ffffff; margin-bottom: 10px; font-size: 20px;">Confidence</h3>
          <p stlye="font-size: 36px; font-weight: 800; color: #2196F3; margin: 0;">
            {prediction[0][class_index]:.4%}
          </p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True
  )

  #Prepare date for Plotly chart
  probabilities = prediction[0]
  sorted_indices = np.argsort(probabilities)[::-1]
  sorted_labels = [labels[i] for i in sorted_indices]
  sorted_probabilities = probabilities[sorted_indices]

  #Create Plotly bar chart
  fig = go.Figure(go.Bar(
      x=sorted_probabilities,
      y=sorted_labels,
      orientation='h',
      marker_color=['red' if label == result else 'blue' for label in sorted_labels]
  ))

  #Customize the chart layout
  fig.update_layout(
      title='Prediction Probabilities',
      xaxis_title='Probability',
      yaxis_title='Class',
      height=400,
      yaxis=dict(autorange='reversed')
  )

  #Add value labels to the bars
  for i, prob in enumerate(sorted_probabilities):
    fig.add_annotation(
        x=prob,
        y=i,
        text=f'{prob:.4f}',
        showarrow=False,
        xanchor='left',
        xshift=5
    )

  #Display the Plotly chart
  st.plotly_chart(fig)



  saliency_map_array = saliency_map.astype(np.uint8)  #Generate Explanation
  explanation = generate_explanation(saliency_map_array, result, prediction[0][class_index])

  st.write("## Explanation")
  st.write(explanation)
